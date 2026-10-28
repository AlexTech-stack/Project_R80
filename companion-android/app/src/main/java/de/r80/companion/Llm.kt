package de.r80.companion

import android.content.Context
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import java.io.IOException
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.net.UnknownHostException
import java.util.concurrent.Executors

/**
 * The LLM for the HU's voice assistant (caps assistant, docs/companion-protocol.md): the HU sends the
 * conversation (assist_request), the app asks the LLM with the user's own API key and sends its message
 * back (assist_reply). Any OpenAI-compatible chat completions API; DeepSeek by default. The key never
 * leaves the phone except to the LLM's own address; nothing of the conversation is kept or logged.
 */
object Llm {
    const val DEFAULT_URL = "https://api.deepseek.com"
    const val DEFAULT_MODEL = "deepseek-flash"
    private const val TIMEOUT_MS = 25_000

    sealed class Result {
        data class Ok(val message: JsonObject, val finish: String, val tokensIn: Int?, val tokensOut: Int?) : Result()
        /** code: no_key | bad_key | no_credit | busy | offline | timeout | server | other */
        data class Err(val code: String, val error: String) : Result()
    }

    /** The provider's short name from its address (api.deepseek.com -> deepseek), for the HU's screen. */
    fun provider(url: String): String {
        val host = try { URL(url).host } catch (_: Exception) { return "" }
        val parts = host.split('.')
        return if (parts.size >= 2) parts[parts.size - 2] else host
    }

    /** The chat completions request: the HU's messages, tools and max_tokens, our model. */
    fun body(request: JsonObject, model: String): String = JsonObject(buildMap {
        put("model", JsonPrimitive(model))
        put("messages", request["messages"] ?: JsonArray(emptyList()))
        (request["tools"] as? JsonArray)?.let { put("tools", it) }
        (request["max_tokens"] as? JsonPrimitive)?.intOrNull?.let { put("max_tokens", JsonPrimitive(it)) }
        put("stream", JsonPrimitive(false))
    }).toString()

    /** The API's answer (HTTP status and body) as a [Result]. */
    fun parse(status: Int, text: String): Result {
        if (status != 200) {
            val why = try {
                ((Json.parseToJsonElement(text).jsonObject["error"] as? JsonObject)?.get("message") as? JsonPrimitive)?.content
            } catch (_: Exception) { null } ?: "HTTP $status"
            return Result.Err(when (status) {
                401, 403 -> "bad_key"
                402 -> "no_credit"
                429 -> "busy"
                in 500..599 -> "server"
                else -> "other"
            }, why.take(Protocol.MAX_TEXT))
        }
        return try {
            val o = Json.parseToJsonElement(text).jsonObject
            val choice = (o["choices"] as JsonArray)[0].jsonObject
            val m = choice["message"]!!.jsonObject
            val message = JsonObject(buildMap {
                put("role", JsonPrimitive("assistant"))
                put("content", m["content"] ?: JsonNull)
                (m["tool_calls"] as? JsonArray)?.takeIf { it.isNotEmpty() }?.let { put("tool_calls", it) }
                (m["reasoning_content"] as? JsonPrimitive)?.takeIf { it.isString }?.let { put("reasoning_content", it) }
            })
            val usage = o["usage"] as? JsonObject
            Result.Ok(message, (choice["finish_reason"] as? JsonPrimitive)?.content ?: "",
                (usage?.get("prompt_tokens") as? JsonPrimitive)?.intOrNull, (usage?.get("completion_tokens") as? JsonPrimitive)?.intOrNull)
        } catch (e: Exception) {
            Result.Err("other", "unexpected answer: ${e.javaClass.simpleName}")
        }
    }

    fun failure(e: Exception): Result.Err = when (e) {
        is UnknownHostException, is ConnectException -> Result.Err("offline", "no internet")
        is SocketTimeoutException -> Result.Err("timeout", "the LLM did not answer in time")
        is IOException -> Result.Err("offline", e.message ?: e.javaClass.simpleName)
        else -> Result.Err("other", e.message ?: e.javaClass.simpleName)
    }

    /** Asks the LLM (blocking: not on the main thread). */
    fun ask(url: String, key: String, model: String, request: JsonObject): Result {
        if (key.isBlank()) return Result.Err("no_key", "no API key in the app")
        return try {
            val c = (URL(url.trimEnd('/') + "/chat/completions").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 10_000
                readTimeout = TIMEOUT_MS
                setRequestProperty("Content-Type", "application/json")
                setRequestProperty("Authorization", "Bearer $key")
            }
            try {
                c.outputStream.use { it.write(body(request, model).toByteArray(Charsets.UTF_8)) }
                val status = c.responseCode
                val text = (if (status == 200) c.inputStream else c.errorStream)?.bufferedReader()?.readText() ?: ""
                parse(status, text)
            } finally {
                c.disconnect()
            }
        } catch (e: Exception) {
            failure(e)
        }
    }

    /** A tiny question, for "Test" in the settings. */
    fun testRequest(): JsonObject = JsonObject(mapOf(
        "messages" to JsonArray(listOf(JsonObject(mapOf("role" to JsonPrimitive("user"),
            "content" to JsonPrimitive("Reply with the single word OK."))))),
        "max_tokens" to JsonPrimitive(200)))
}

/** The link's side of the voice assistant: whether we can answer, and the answers, one at a time. */
interface AssistantRelay {
    /** An assist_status line. */
    fun status(): String
    /** Answers request [id] on its own thread; [reply] gets the assist_reply line. */
    fun answer(id: Int, request: JsonObject, reply: (String) -> Unit)
}

/** The real one: the user's key and model from [Settings], [Llm] over HTTPS. */
class AppAssistant(private val ctx: Context) : AssistantRelay {
    private val worker = Executors.newSingleThreadExecutor { Thread(it, "r80-llm").apply { isDaemon = true } }

    override fun status(): String {
        val url = Settings.llmUrl(ctx)
        val ready = Settings.assistant(ctx) && Secret.has(ctx)
        val reason = when {
            !Settings.assistant(ctx) -> "switched off in the app"
            !ready -> "no API key in the app"
            else -> ""
        }
        return Protocol.assistStatus(ready, Llm.provider(url), Settings.llmModel(ctx), reason)
    }

    override fun answer(id: Int, request: JsonObject, reply: (String) -> Unit) {
        worker.execute {
            val t0 = System.nanoTime()
            val r = if (!Settings.assistant(ctx)) Llm.Result.Err("no_key", "switched off in the app")
                    else Llm.ask(Settings.llmUrl(ctx), Secret.load(ctx), Settings.llmModel(ctx), request)
            val ms = (System.nanoTime() - t0) / 1_000_000
            AppState.setAssist(r, ms)
            reply(try {
                when (r) {
                    is Llm.Result.Ok -> Protocol.assistReply(id, r.message, r.finish, r.tokensIn, r.tokensOut, ms)
                    is Llm.Result.Err -> Protocol.assistError(id, r.code, r.error, ms)
                }
            } catch (e: IllegalArgumentException) {               // longer than a line: say so instead
                Protocol.assistError(id, "other", "answer too long for the link", ms)
            })
        }
    }
}
