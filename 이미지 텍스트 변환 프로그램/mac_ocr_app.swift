import SwiftUI
import Vision
import AppKit
import UniformTypeIdentifiers

@main
struct OCRApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .frame(minWidth: 700, minHeight: 520)
        }
        .windowStyle(.hiddenTitleBar)
    }
}

struct ContentView: View {
    @State private var recognizedText: String = ""
    @State private var isProcessing: Bool = false
    @State private var statusMessage: String = "이미지 선택, 드래그 앤 드롭 또는 붙여넣기(Cmd + V)로 글자를 추출할 수 있습니다."
    @State private var statusColor: Color = .secondary
    @State private var selectedImageName: String = ""
    @State private var currentBaseName: String = "이미지 추출"
    @State private var isTargeted: Bool = false
    
    var body: some View {
        ZStack {
            // macOS Native Translucent Background (Glassmorphism)
            VisualEffectView(material: .hudWindow, blendingMode: .behindWindow)
                .ignoresSafeArea()
            
            VStack(spacing: 0) {
                // Header (App Title Bar)
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("이미지 글자 추출기 (OCR)")
                            .font(.system(size: 20, weight: .bold))
                            .foregroundColor(.primary)
                        
                        Text("한글 & 영어 추출 • macOS 내장 고성능 Vision 엔진 사용")
                            .font(.system(size: 11))
                            .foregroundColor(.secondary)
                    }
                    Spacer()
                }
                .padding(.horizontal, 24)
                .padding(.top, 24)
                .padding(.bottom, 16)
                
                Divider().opacity(0.1)
                
                // Content Area
                VStack(spacing: 16) {
                    // Controls (Select Button, Paste Button & Status)
                    HStack(spacing: 12) {
                        // 1. File Select Button
                        Button(action: selectImage) {
                            HStack {
                                Image(systemName: "photo.on.rectangle")
                                Text("이미지 파일 선택")
                            }
                            .font(.system(size: 13, weight: .semibold))
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(Color.blue)
                        
                        // 2. Clipboard Paste Button
                        Button(action: pasteImageFromClipboard) {
                            HStack {
                                Image(systemName: "doc.on.clipboard")
                                Text("클립보드 붙여넣기")
                            }
                            .font(.system(size: 13, weight: .semibold))
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                        }
                        .buttonStyle(.bordered)
                        .keyboardShortcut("v", modifiers: .command)
                        
                        // Spacer
                        Spacer()
                    }
                    .padding(.horizontal, 24)
                    .padding(.top, 16)
                    
                    // Status Indicator Row
                    HStack(spacing: 6) {
                        if isProcessing {
                            ProgressView()
                                .scaleEffect(0.6)
                                .frame(width: 16, height: 16)
                        } else {
                            Circle()
                                .fill(statusColor)
                                .frame(width: 8, height: 8)
                        }
                        
                        Text(statusMessage)
                            .font(.system(size: 12))
                            .foregroundColor(.primary)
                            .lineLimit(1)
                        
                        Spacer()
                    }
                    .padding(.horizontal, 24)
                    
                    // Main Text Output Display
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("추출된 텍스트")
                                .font(.system(size: 13, weight: .semibold))
                                .foregroundColor(.secondary)
                            Spacer()
                            
                            if !recognizedText.isEmpty {
                                HStack(spacing: 8) {
                                    // 3. Save Text To File Button
                                    Button(action: saveTextToFile) {
                                        Label("텍스트 파일로 저장", systemImage: "square.and.arrow.down")
                                            .font(.system(size: 11))
                                    }
                                    .buttonStyle(.bordered)
                                    .buttonBorderShape(.capsule)
                                    
                                    // 4. Copy to Clipboard Button
                                    Button(action: copyToClipboard) {
                                        Label("클립보드 복사", systemImage: "doc.on.doc")
                                            .font(.system(size: 11))
                                    }
                                    .buttonStyle(.bordered)
                                    .buttonBorderShape(.capsule)
                                }
                            }
                        }
                        .padding(.horizontal, 24)
                        
                        ZStack {
                            // Dark background card for text
                            RoundedRectangle(cornerRadius: 12)
                                .fill(Color(NSColor.controlBackgroundColor).opacity(0.6))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 12)
                                        .stroke(Color.white.opacity(0.1), lineWidth: 1)
                                )
                            
                            if isProcessing {
                                VStack(spacing: 12) {
                                    ProgressView()
                                        .controlSize(.large)
                                    Text("이미지 내 글자를 분석하는 중입니다...")
                                        .font(.system(size: 13))
                                        .foregroundColor(.secondary)
                                }
                            } else {
                                if recognizedText.isEmpty {
                                    VStack(spacing: 12) {
                                        Image(systemName: "text.magnifyingglass")
                                            .font(.system(size: 36))
                                            .foregroundColor(.secondary.opacity(0.6))
                                        Text("이미지 파일을 불러오거나, 여기에 드래그 앤 드롭 하거나, 붙여넣기(Cmd + V) 하세요.")
                                            .font(.system(size: 13))
                                            .foregroundColor(.secondary)
                                    }
                                } else {
                                    TextEditor(text: $recognizedText)
                                        .font(.system(.body, design: .monospaced))
                                        .scrollContentBackground(.hidden)
                                        .padding(12)
                                }
                            }
                        }
                        .padding(.horizontal, 24)
                    }
                }
                
                // Footer bar
                HStack {
                    Text("텍스트 추출 후 우측 상단의 '텍스트 파일로 저장' 버튼을 통해 파일로 저장할 수 있습니다.")
                        .font(.system(size: 10))
                        .foregroundColor(.secondary)
                    Spacer()
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 16)
            }
            
            // Drag and Drop Visual Feedback Overlay
            if isTargeted {
                RoundedRectangle(cornerRadius: 16)
                    .strokeBorder(Color.blue, style: StrokeStyle(lineWidth: 3, dash: [10, 5]))
                    .background(Color.blue.opacity(0.08))
                    .overlay(
                        VStack(spacing: 12) {
                            Image(systemName: "square.and.arrow.down.on.square.fill")
                                .font(.system(size: 48))
                                .foregroundColor(.blue)
                            Text("이미지 파일을 여기에 떨어뜨려 놓으세요")
                                .font(.system(size: 16, weight: .bold))
                                .foregroundColor(.blue)
                        }
                    )
                    .padding(16)
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut, value: isTargeted)
        .onDrop(of: [.fileURL], isTargeted: $isTargeted) { providers in
            let group = DispatchGroup()
            var collectedURLs: [URL] = []
            let urlLock = NSLock()
            
            for provider in providers {
                group.enter()
                provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, error in
                    defer { group.leave() }
                    guard let data = item as? Data,
                          let url = URL(dataRepresentation: data, relativeTo: nil) else { return }
                    
                    let ext = url.pathExtension.lowercased()
                    let allowed = ["png", "jpg", "jpeg", "tiff", "webp", "bmp", "gif"]
                    if allowed.contains(ext) {
                        urlLock.lock()
                        collectedURLs.append(url)
                        urlLock.unlock()
                    }
                }
            }
            
            group.notify(queue: .main) {
                if !collectedURLs.isEmpty {
                    // Sort collected URLs alphabetically to preserve some order
                    collectedURLs.sort { $0.lastPathComponent < $1.lastPathComponent }
                    
                    if collectedURLs.count == 1 {
                        self.selectedImageName = collectedURLs[0].lastPathComponent
                    } else {
                        self.selectedImageName = "\(collectedURLs[0].lastPathComponent) 외 \(collectedURLs.count - 1)개"
                    }
                    self.performOCR(for: collectedURLs)
                } else {
                    self.updateStatus(message: "지원하지 않는 파일 형식입니다. 이미지 파일만 드롭해 주세요.", color: .red, isDone: true)
                }
            }
            return true
        }
    }
    
    // File open dialog & Trigger OCR
    func selectImage() {
        let openPanel = NSOpenPanel()
        openPanel.title = "텍스트를 추출할 이미지 선택"
        openPanel.showsHiddenFiles = false
        openPanel.canChooseDirectories = false
        openPanel.canChooseFiles = true
        openPanel.allowsMultipleSelection = true
        
        // Define allowable image types
        openPanel.allowedContentTypes = [.image]
        
        openPanel.begin { response in
            if response == .OK {
                let urls = openPanel.urls
                if !urls.isEmpty {
                    if urls.count == 1 {
                        self.selectedImageName = urls[0].lastPathComponent
                    } else {
                        self.selectedImageName = "\(urls[0].lastPathComponent) 외 \(urls.count - 1)개"
                    }
                    self.performOCR(for: urls)
                }
            }
        }
    }
    
    // Paste Image from clipboard & Trigger OCR
    func pasteImageFromClipboard() {
        let pasteboard = NSPasteboard.general
        
        // 1. Check for TIFF data (copied raw image)
        if let tiffData = pasteboard.data(forType: .tiff),
           let nsImage = NSImage(data: tiffData) {
            self.selectedImageName = "이미지 텍스트 추출"
            self.performOCR(for: nsImage, sourceName: "이미지 텍스트 추출")
            return
        }
        
        // 2. Check for File URL on pasteboard (copied image file from Finder)
        if let fileURLs = pasteboard.readObjects(forClasses: [NSURL.self], options: nil) as? [URL],
           let firstURL = fileURLs.first {
            let ext = firstURL.pathExtension.lowercased()
            let allowed = ["png", "jpg", "jpeg", "tiff", "webp", "bmp", "gif"]
            if allowed.contains(ext) {
                self.selectedImageName = firstURL.lastPathComponent
                self.performOCR(for: [firstURL])
                return
            }
        }
        
        // 3. Fallback: No image
        self.updateStatus(message: "클립보드에 이미지 또는 이미지 파일이 존재하지 않습니다.", color: .red, isDone: true)
    }
    
    // Perform OCR for multiple local file URLs
    func performOCR(for imageUrls: [URL]) {
        self.isProcessing = true
        self.statusMessage = "총 \(imageUrls.count)개 이미지 분석 중..."
        self.statusColor = .orange
        
        // Append text to support continuous dropping/loading without losing previous text
        DispatchQueue.global(qos: .userInitiated).async {
            var accumulatedText = self.recognizedText
            var successCount = 0
            
            for url in imageUrls {
                guard let image = NSImage(contentsOf: url),
                      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
                    continue
                }
                
                let baseName = url.deletingPathExtension().lastPathComponent
                
                let request = VNRecognizeTextRequest()
                request.recognitionLevel = .accurate
                request.recognitionLanguages = ["ko-KR", "en-US"]
                request.usesLanguageCorrection = true
                
                let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
                do {
                    try handler.perform([request])
                    
                    if let observations = request.results {
                        var lines: [String] = []
                        for observation in observations {
                            if let candidate = observation.topCandidates(1).first {
                                lines.append(candidate.string)
                            }
                        }
                        let fileResult = lines.joined(separator: "\n")
                        
                        if !fileResult.isEmpty {
                            if !accumulatedText.isEmpty {
                                accumulatedText += "\n\n"
                            }
                            accumulatedText += "--- [\(baseName)] ---\n" + fileResult
                            successCount += 1
                        }
                    }
                } catch {
                    print("Error performing Vision OCR for \(baseName): \(error.localizedDescription)")
                }
            }
            
            // Set base name for manual text file saving
            let finalBaseName: String
            if imageUrls.count == 1 {
                finalBaseName = imageUrls[0].deletingPathExtension().lastPathComponent
            } else {
                let firstBase = imageUrls[0].deletingPathExtension().lastPathComponent
                finalBaseName = "\(firstBase)_외_\(imageUrls.count - 1)개"
            }
            
            DispatchQueue.main.async {
                self.isProcessing = false
                self.recognizedText = accumulatedText
                self.currentBaseName = finalBaseName
                if successCount == 0 {
                    self.statusMessage = "인식된 글자가 없습니다."
                    self.statusColor = .gray
                } else {
                    self.statusMessage = "성공: \(imageUrls.count)개 중 \(successCount)개 이미지 추출 완료!"
                    self.statusColor = .green
                }
            }
        }
    }
    
    // Overload performOCR for raw memory image (Clipboard)
    func performOCR(for image: NSImage, sourceName: String) {
        self.isProcessing = true
        self.statusMessage = "분석 중: \(sourceName)"
        self.statusColor = .orange
        self.recognizedText = ""
        
        DispatchQueue.global(qos: .userInitiated).async {
            self.runVisionOCR(for: image, baseName: sourceName)
        }
    }
    
    // Core OCR Execution using Apple Vision Framework
    func runVisionOCR(for image: NSImage, baseName: String) {
        // Get CGImage representation
        guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            self.updateStatus(message: "오류: 이미지 변환에 실패했습니다.", color: .red, isDone: true)
            return
        }
        
        // Vision recognize text request
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["ko-KR", "en-US"] // Support Korean and English
        request.usesLanguageCorrection = true
        
        let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
        do {
            try handler.perform([request])
            
            guard let observations = request.results else {
                self.updateStatus(message: "인식 결과가 존재하지 않습니다.", color: .gray, isDone: true)
                return
            }
            
            // Parse extracted lines
            var lines: [String] = []
            for observation in observations {
                if let candidate = observation.topCandidates(1).first {
                    lines.append(candidate.string)
                }
            }
            let finalResult = lines.joined(separator: "\n")
            
            // Update UI on Main thread
            DispatchQueue.main.async {
                self.isProcessing = false
                self.recognizedText = finalResult
                self.currentBaseName = baseName
                if finalResult.isEmpty {
                    self.statusMessage = "인식된 글자가 없습니다."
                    self.statusColor = .gray
                } else {
                    self.statusMessage = "성공: 글자 추출 완료!"
                    self.statusColor = .green
                }
            }
        } catch {
            self.updateStatus(message: "실패: \(error.localizedDescription)", color: .red, isDone: true)
        }
    }
    
    // Save extracted text to file manually
    func saveTextToFile() {
        let savePanel = NSSavePanel()
        savePanel.title = "텍스트 파일로 저장"
        savePanel.allowedContentTypes = [.text]
        
        let formatter = DateFormatter()
        formatter.dateFormat = "yyMMdd_HHmmss"
        let timestamp = formatter.string(from: Date())
        
        let defaultName = "\(currentBaseName)_\(timestamp).txt"
        savePanel.nameFieldStringValue = defaultName
        
        savePanel.begin { response in
            if response == .OK, let url = savePanel.url {
                do {
                    try recognizedText.write(to: url, atomically: true, encoding: .utf8)
                    self.statusMessage = "수동 저장 성공: \(url.lastPathComponent)"
                    self.statusColor = .green
                } catch {
                    self.statusMessage = "저장 실패: \(error.localizedDescription)"
                    self.statusColor = .red
                }
            }
        }
    }
    
    // Utility function to update status from background threads safely
    func updateStatus(message: String, color: Color, isDone: Bool) {
        DispatchQueue.main.async {
            self.statusMessage = message
            self.statusColor = color
            if isDone {
                self.isProcessing = false
            }
        }
    }
    
    // Copy extracted text to Clipboard
    func copyToClipboard() {
        let pasteboard = NSPasteboard.general
        pasteboard.declareTypes([.string], owner: nil)
        pasteboard.setString(recognizedText, forType: .string)
    }
}

// SwiftUI Helper: macOS Visual Effect View (for translucency/glassmorphism)
struct VisualEffectView: NSViewRepresentable {
    var material: NSVisualEffectView.Material
    var blendingMode: NSVisualEffectView.BlendingMode
    
    func makeNSView(context: Context) -> NSVisualEffectView {
        let visualEffectView = NSVisualEffectView()
        visualEffectView.material = material
        visualEffectView.blendingMode = blendingMode
        visualEffectView.state = .active
        return visualEffectView
    }
    
    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
        nsView.blendingMode = blendingMode
    }
}
