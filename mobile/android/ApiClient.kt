import java.net.HttpURLConnection
import java.net.URL
import org.json.JSONObject
import org.json.JSONArray
// Android skeleton for Logistics AI SaaS. Set BASE_URL to your SaaS server.
// On a real phone, use your computer's LAN IP, e.g. http://192.168.1.10:8000
object ApiClient {
    const val BASE_URL = "http://10.0.2.2:8000" // Android emulator -> host localhost
    fun shipments(): String {
        val c = URL("$BASE_URL/api/shipments").openConnection() as HttpURLConnection
        return c.inputStream.bufferedReader().readText()
    }
    fun chat(message: String): String {
        val c = URL("$BASE_URL/api/chat").openConnection() as HttpURLConnection
        c.requestMethod = "POST"; c.setRequestProperty("Content-Type", "application/json"); c.doOutput = true
        c.outputStream.write(JSONObject().put("message", message).toString().toByteArray())
        val obj = JSONObject(c.inputStream.bufferedReader().readText())
        return obj.optString("reply", "No reply from server.")
    }
}
