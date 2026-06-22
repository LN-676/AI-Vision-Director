import SwiftUI

struct ContentView: View {
    @ObservedObject var dockKitManager: DockKitManager
    @ObservedObject var cameraSession: CameraSessionService
    @ObservedObject var controlService: GimbalControlService
    @ObservedObject var networkClient: V13NetworkClient
    @ObservedObject var logger: AppLogger
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    cameraPanel
                    safetyNotice
                    StatusPanelView(
                        manager: dockKitManager,
                        onTestVelocity: { await controlService.testAngularVelocity() }
                    )
                    ManualControlPadView(
                        isDocked: dockKitManager.isDocked,
                        isManualControlReady: dockKitManager.isManualControlReady,
                        onCommand: { await controlService.execute($0) }
                    )
                    velocityPanel
                    NetworkTestView(
                        client: networkClient,
                        canInjectCommand: dockKitManager.isManualControlReady
                    )
                    LogConsoleView(logger: logger)
                }
                .padding()
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("DockKit Tester")
        }
        .task {
            networkClient.onCommand = { [weak controlService] command in
                await controlService?.apply(command)
            }
            networkClient.onTimeout = { [weak controlService] in
                await controlService?.emergencyStop(reason: "V1.3 timeout or disconnect")
            }
            await cameraSession.start()
            await dockKitManager.startListening()
        }
        .onChange(of: scenePhase) { _, newPhase in
            Task {
                if newPhase == .active {
                    await cameraSession.start()
                } else {
                    await controlService.emergencyStop(reason: "app left foreground")
                    await cameraSession.stop()
                }
            }
        }
    }

    private var cameraPanel: some View {
        ZStack(alignment: .bottomLeading) {
            CameraPreviewView(session: cameraSession.session)
                .frame(height: 220)
                .clipShape(RoundedRectangle(cornerRadius: 14))

            Label(
                cameraSession.isRunning ? "Camera Active" : "Camera Inactive",
                systemImage: cameraSession.isRunning ? "camera.fill" : "camera.slash.fill"
            )
            .font(.caption.weight(.semibold))
            .foregroundStyle(.white)
            .padding(8)
            .background(.black.opacity(0.65), in: Capsule())
            .padding(10)
        }
    }

    private var safetyNotice: some View {
        Label(
            "先進入 Manual Mode 並確認 Tracking OFF。方向鍵會持續輸出速度，測完請立即按 STOP。",
            systemImage: "exclamationmark.triangle.fill"
        )
        .font(.footnote.weight(.semibold))
        .foregroundStyle(.orange)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 12))
    }

    private var velocityPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Current Command")
                .font(.headline)
            Text(
                String(
                    format: "yaw %.3f   pitch %.3f   roll %.3f rad/s",
                    controlService.currentVelocity.yaw,
                    controlService.currentVelocity.pitch,
                    controlService.currentVelocity.roll
                )
            )
            .font(.system(.body, design: .monospaced))
        }
        .panelStyle()
    }
}

private extension View {
    func panelStyle() -> some View {
        frame(maxWidth: .infinity, alignment: .leading)
            .padding()
            .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 14))
    }
}
