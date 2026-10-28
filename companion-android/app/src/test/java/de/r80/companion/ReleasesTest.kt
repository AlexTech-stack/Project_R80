package de.r80.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** GitHub's "latest release" answer (parts of it) -> the HU's update file. */
class ReleasesTest {
    private fun answer(name: String, size: Long = 368640, url: String = "https://github.com/AlexTech-stack/Project_R80/releases/download/v0.1.0/$name") = """
        {"tag_name":"v0.1.0","name":"R80 HU 0.1.0","assets":[
          {"name":"notes.txt","size":10,"browser_download_url":"https://example.org/notes.txt"},
          {"name":"$name","size":$size,"browser_download_url":"$url"}]}"""

    @Test fun findsTheUpdateFile() {
        assertEquals(Releases.Release("0.1.0", "r80-hu-0.1.0.r80u",
            "https://github.com/AlexTech-stack/Project_R80/releases/download/v0.1.0/r80-hu-0.1.0.r80u", 368640),
            Releases.parseLatest(answer("r80-hu-0.1.0.r80u")))
    }

    @Test fun skipsWhatIsNotOne() {
        assertNull(Releases.parseLatest(answer("r80-hu-latest.r80u")))                // not a version
        assertNull(Releases.parseLatest(answer("r80-hu-0.1.0.r80u", size = 0)))
        assertNull(Releases.parseLatest(answer("r80-hu-0.1.0.r80u", url = "http://example.org/x")))
        assertNull(Releases.parseLatest("""{"message":"Not Found"}"""))
        assertNull(Releases.parseLatest("not json"))
    }
}
