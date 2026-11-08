import SwiftUI
// SwiftUI skeleton: shipment list + chatbot. Wire ApiClient above.
// In Xcode: create a new iOS App project, add LogisticsAIApp.swift,
// ContentView.swift, and ApiClient.swift, then Run.
struct ContentView: View {
    @State private var shipments: [[String: Any]] = []
    @State private var chatInput = ""
    @State private var chatLog = "Ask: Which trucks are delayed? / What is TRK-101 ETA?"
    var body: some View {
        TabView {
            List {
                ForEach(shipments.indices, id: \.self) { i in
                    let s = shipments[i]
                    VStack(alignment: .leading) {
                        Text(s["id"] as? String ?? "").bold()
                        Text("\(s["origin"] as? String ?? "") → \(s["destination"] as? String ?? "")")
                        Text("Status: \(s["status"] as? String ?? "")")
                    }
                }
            }
            .tabItem { Label("Shipments", systemImage: "truck.box") }
            .task { shipments = (try? await ApiClient.shipments()) ?? [] }
            VStack {
                ScrollView { Text(chatLog).frame(maxWidth: .infinity, alignment: .leading).padding() }
                HStack {
                    TextField("Ask the AI chatbot…", text: $chatInput)
                    Button("Send") {
                        let q = chatInput; chatInput = ""
                        Task { let r = try? await ApiClient.chat(message: q); chatLog += "\n\nYou: \(q)\nAI: \(r ?? "")" }
                    }
                }.padding()
            }
            .tabItem { Label("AI Chat", systemImage: "message") }
        }
    }
}
