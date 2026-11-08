import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
// Kotlin / Jetpack Compose skeleton: shipment list + chatbot.
// In Android Studio: create a new Compose project, add ApiClient.kt + this file, Run.
// Network calls must run off the main thread in production (use coroutines / ViewModel).
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            var chatInput by remember { mutableStateOf("") }
            var chatLog by remember { mutableStateOf("Ask: Which trucks are delayed? / What is TRK-101 ETA?") }
            Column(Modifier.padding(16.dp)) {
                Text("Logistics AI — Mobile", style = MaterialTheme.typography.headlineSmall)
                Text("Shipments: open /api/shipments in the SaaS server. This skeleton shows the chatbot; wire the list to ApiClient.shipments() with coroutines.")
                Spacer(Modifier.height(16.dp))
                Text(chatLog)
                Spacer(Modifier.height(16.dp))
                TextField(value = chatInput, onValueChange = { chatInput = it }, label = { Text("Ask the AI chatbot…") })
                Button(onClick = {
                    val q = chatInput; chatInput = ""
                    Thread { val r = runCatching { ApiClient.chat(q) }.getOrDefault("Error"); runOnUiThread { chatLog += "\n\nYou: $q\nAI: $r" } }.start()
                }) { Text("Send") }
            }
        }
    }
}
