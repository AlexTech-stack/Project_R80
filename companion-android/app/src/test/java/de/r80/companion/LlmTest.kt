package de.r80.companion

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/** The voice assistant's LLM calls (OpenAI-compatible chat completions), without the network. */
class LlmTest {
    private val request = Json.parseToJsonElement("""{"type":"assist_request","id":3,"max_tokens":800,
        "messages":[{"role":"system","content":"Be short."},{"role":"user","content":"Hi"}],
        "tools":[{"type":"function","function":{"name":"vehicle","parameters":{"type":"object"}}}]}""").jsonObject

    @Test fun bodyCarriesTheHusMessagesAndOurModel() {
        val b = Json.parseToJsonElement(Llm.body(request, "deepseek-flash")).jsonObject
        assertEquals(JsonPrimitive("deepseek-flash"), b["model"])
        assertEquals(request["messages"], b["messages"])
        assertEquals(request["tools"], b["tools"])
        assertEquals(JsonPrimitive(800), b["max_tokens"])
        assertEquals(JsonPrimitive(false), b["stream"])
        assertFalse("the HU's own fields stay out", "id" in b || "type" in b)
    }

    @Test fun anAnswer() {
        val r = Llm.parse(200, """{"choices":[{"index":0,"message":{"role":"assistant","content":"Hello.",
            "reasoning_content":"The user greets."},"finish_reason":"stop"}],"usage":{"prompt_tokens":70,"completion_tokens":52}}""")
        r as Llm.Result.Ok
        assertEquals(JsonPrimitive("Hello."), r.message["content"])
        assertEquals(JsonPrimitive("The user greets."), r.message["reasoning_content"])
        assertEquals("stop", r.finish)
        assertEquals(70, r.tokensIn)
        assertEquals(52, r.tokensOut)
    }

    @Test fun toolCallsComeThrough() {
        val r = Llm.parse(200, """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"index":0,
            "id":"call_0","type":"function","function":{"name":"vehicle","arguments":"{}"}}]},"finish_reason":"tool_calls"}]}""")
        r as Llm.Result.Ok
        assertEquals(JsonNull, r.message["content"])
        assertEquals(1, (r.message["tool_calls"] as JsonArray).size)
        assertEquals("tool_calls", r.finish)
        // and fits the protocol: the HU takes it
        val line = Protocol.assistReply(4, r.message, r.finish, r.tokensIn, r.tokensOut, 900)
        assertTrue(line.contains("\"tool_calls\""))
    }

    @Test fun errorsHaveTheProtocolsCodes() {
        val err = """{"error":{"message":"Authentication Fails, Your api key is invalid","type":"authentication_error"}}"""
        assertEquals(Llm.Result.Err("bad_key", "Authentication Fails, Your api key is invalid"), Llm.parse(401, err))
        assertEquals("no_credit", (Llm.parse(402, "{}") as Llm.Result.Err).code)
        assertEquals("busy", (Llm.parse(429, "") as Llm.Result.Err).code)
        assertEquals("server", (Llm.parse(503, "<html>") as Llm.Result.Err).code)
        assertEquals("other", (Llm.parse(200, "not json") as Llm.Result.Err).code)
        assertEquals("offline", Llm.failure(UnknownHostException("api.deepseek.com")).code)
        assertEquals("timeout", Llm.failure(SocketTimeoutException()).code)
        assertEquals("no_key", (Llm.ask(Llm.DEFAULT_URL, " ", "m", request) as Llm.Result.Err).code)
    }

    @Test fun providerFromTheAddress() {
        assertEquals("deepseek", Llm.provider("https://api.deepseek.com"))
        assertEquals("openai", Llm.provider("https://api.openai.com/v1"))
        assertEquals("", Llm.provider("not a url"))
    }

    @Test fun replyLinesFitTheHusLimits() {
        val msg = JsonObject(mapOf("role" to JsonPrimitive("assistant"), "content" to JsonPrimitive("x".repeat(20_000))))
        assertTrue(Protocol.assistReply(1, msg, "stop", null, null, 1).length < Protocol.MAX_LINE)
    }
}
