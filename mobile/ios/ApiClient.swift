import Foundation
// iOS app for Logistics AI SaaS. Set BASE_URL to your SaaS server.
// On a real phone, use your computer's LAN IP, e.g. http://192.168.1.10:8000
// Also add NSAllowsArbitraryLoads = YES to Info.plist (see INSTALL_IOS.md),
// otherwise iOS blocks this plain-http demo server.
struct ApiClient {
    static let BASE_URL = "http://127.0.0.1:8000"
    static func shipments() async throws -> [[String: Any]] {
        let url = URL(string: BASE_URL + "/api/shipments")!
        let (data, _) = try await URLSession.shared.data(from: url)
        return try JSONSerialization.jsonObject(with: data) as? [[String: Any]] ?? []
    }
    static func chat(message: String) async throws -> String {
        let url = URL(string: BASE_URL + "/api/chat")!
        var req = URLRequest(url: url); req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["message": message])
        let (data, _) = try await URLSession.shared.data(for: req)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return obj?["reply"] as? String ?? "No reply from server."
    }
}
