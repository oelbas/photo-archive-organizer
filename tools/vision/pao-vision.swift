// pao-vision: local, on-device image checks for photo-archive-organizer.
// Nothing is uploaded and no picture is shown; only numbers are printed.
//
//   pao-vision fp <queries.txt> <references.txt> <out.tsv> [--rotate]
//       For each query: "query \t nearest-distance \t nearest-reference".
//       --rotate also compares the query turned 90/180/270 degrees, so a
//       rotated copy still matches.
//   pao-vision decode <list.txt>
//       "OK|BAD \t WxH \t gray-fraction \t path" per image. gray-fraction is
//       the share of the bottom half that is flat mid-gray, the usual sign of a
//       truncated JPEG.
import AppKit
import Foundation
import ImageIO
import Vision

func readList(_ path: String) -> [String] {
    guard let s = try? String(contentsOfFile: path, encoding: .utf8) else { return [] }
    return s.split(separator: "\n").map(String.init).filter { !$0.isEmpty }
}

func featurePrint(_ path: String, _ orientation: CGImagePropertyOrientation = .up) -> VNFeaturePrintObservation? {
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: path), orientation: orientation, options: [:])
    let req = VNGenerateImageFeaturePrintRequest()
    do { try handler.perform([req]) } catch { return nil }
    return req.results?.first as? VNFeaturePrintObservation
}

func cmdFP(_ args: [String]) {
    guard args.count >= 3 else { print("usage: pao-vision fp queries.txt refs.txt out.tsv [--rotate]"); exit(2) }
    let rotate = args.contains("--rotate")
    let queries = readList(args[0]), refs = readList(args[1])
    var refPrints: [(String, VNFeaturePrintObservation)] = []
    for p in refs { autoreleasepool { if let o = featurePrint(p) { refPrints.append((p, o)) } } }
    FileHandle.standardError.write("references \(refPrints.count)/\(refs.count)\n".data(using: .utf8)!)
    let turns: [CGImagePropertyOrientation] = rotate ? [.up, .right, .down, .left] : [.up]
    var out = ""
    for (i, q) in queries.enumerated() {
        autoreleasepool {
            var best = Float.greatestFiniteMagnitude, bestPath = ""
            for t in turns {
                guard let qo = featurePrint(q, t) else { continue }
                for (rp, ro) in refPrints {
                    var d = Float(0)
                    if (try? qo.computeDistance(&d, to: ro)) != nil, d < best { best = d; bestPath = rp }
                }
            }
            if bestPath.isEmpty { out += "\(q)\t\t\n" } else { out += "\(q)\t\(best)\t\(bestPath)\n" }
        }
        if i % 200 == 0 { FileHandle.standardError.write("queries \(i)/\(queries.count)\n".data(using: .utf8)!) }
    }
    try? out.write(toFile: args[2], atomically: true, encoding: .utf8)
    print("ok \(queries.count)")
}

func cmdDecode(_ args: [String]) {
    guard args.count >= 1 else { print("usage: pao-vision decode list.txt"); exit(2) }
    for p in readList(args[0]) {
        autoreleasepool {
            var ok = false, size = "", gray = 1.0
            if let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: p) as CFURL, nil),
               CGImageSourceGetCount(src) > 0,
               let img = CGImageSourceCreateImageAtIndex(src, 0, [kCGImageSourceShouldCacheImmediately: true] as CFDictionary) {
                let w = 64, h = 64
                if let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                       space: CGColorSpaceCreateDeviceRGB(),
                                       bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) {
                    ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
                    if let data = ctx.data {
                        let px = data.bindMemory(to: UInt8.self, capacity: w * h * 4)
                        var flat = 0, total = 0
                        // CGContext rows start at the top; the bottom half is rows h/2..<h
                        for y in (h / 2)..<h { for x in 0..<w {
                            let o = (y * w + x) * 4
                            let r = Int(px[o]), g = Int(px[o + 1]), b = Int(px[o + 2])
                            if abs(r - 128) < 6 && abs(g - 128) < 6 && abs(b - 128) < 6 { flat += 1 }
                            total += 1
                        } }
                        gray = Double(flat) / Double(max(total, 1))
                    }
                    ok = true
                    size = "\(img.width)x\(img.height)"
                }
            }
            print("\(ok ? "OK" : "BAD")\t\(size)\t\(String(format: "%.3f", ok ? gray : 1.0))\t\(p)")
        }
    }
}

let argv = Array(CommandLine.arguments.dropFirst())
guard let cmd = argv.first else { print("usage: pao-vision fp|decode ..."); exit(2) }
switch cmd {
case "fp": cmdFP(Array(argv.dropFirst()))
case "decode": cmdDecode(Array(argv.dropFirst()))
default: print("unknown command \(cmd)"); exit(2)
}
