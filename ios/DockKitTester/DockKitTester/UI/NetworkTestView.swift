import SwiftUI

struct NetworkTestView: View {
    @ObservedObject var client: V13NetworkClient
    let canInjectCommand: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("V1.3 Network Stub")
                    .font(.headline)
                Spacer()
                Text(client.status.rawValue)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }

            if let command = client.lastCommand {
                Text(
                    String(
                        format: "locked=%@  error_x=%.3f  error_y=%.3f  confidence=%.2f",
                        String(command.targetLocked),
                        command.errorX,
                        command.errorY,
                        command.confidence
                    )
                )
                .font(.system(.caption, design: .monospaced))
            }

            Button("Inject Fake JSON") {
                Task { await client.sendFakeCommand() }
            }
            .buttonStyle(.bordered)
            .disabled(!canInjectCommand)

            Text("Fake data drives the same control loop and triggers STOP after 500 ms without another message.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 14))
    }
}
