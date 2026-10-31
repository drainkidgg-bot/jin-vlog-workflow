// 抠图：用 macOS Vision 的前景分割（和"照片"里「拷贝主体」同一能力），输出透明背景 PNG。
// 封面上要叠一个产品、一只手拿着的设备时用。只能在 macOS 14+ 上跑。
// 用法：swift lift_subject.swift 输入.png 输出.png [实例序号,逗号分隔；省略则全部]
// 会顺带把每个实例的遮罩存成 输出.mask<序号>.png，先看遮罩再决定要哪几个实例。
import Foundation
import Vision
import CoreImage
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
guard args.count >= 3 else { print("用法：swift lift_subject.swift 输入.png 输出.png [实例序号]"); exit(1) }
let input = URL(fileURLWithPath: args[1])
let output = URL(fileURLWithPath: args[2])

let handler = VNImageRequestHandler(url: input)
let request = VNGenerateForegroundInstanceMaskRequest()
try handler.perform([request])
guard let result = request.results?.first else { print("没找到主体"); exit(1) }

let all = result.allInstances
print("实例:", all.map { $0 })
var chosen = all
if args.count > 3 { chosen = IndexSet(args[3].split(separator: ",").compactMap { Int($0) }) }

let buffer = try result.generateMaskedImage(ofInstances: chosen, from: handler, croppedToInstancesExtent: false)
let ci = CIImage(cvPixelBuffer: buffer)
let ctx = CIContext()
guard let cg = ctx.createCGImage(ci, from: ci.extent),
      let dest = CGImageDestinationCreateWithURL(output as CFURL, UTType.png.identifier as CFString, 1, nil) else { exit(1) }
CGImageDestinationAddImage(dest, cg, nil)
CGImageDestinationFinalize(dest)

for i in all {
    let m = try result.generateScaledMaskForImage(forInstances: IndexSet(integer: i), from: handler)
    let mi = CIImage(cvPixelBuffer: m)
    if let mcg = ctx.createCGImage(mi, from: mi.extent),
       let d = CGImageDestinationCreateWithURL(output.deletingPathExtension().appendingPathExtension("mask\(i).png") as CFURL, UTType.png.identifier as CFString, 1, nil) {
        CGImageDestinationAddImage(d, mcg, nil); CGImageDestinationFinalize(d)
    }
}
print("ok")
