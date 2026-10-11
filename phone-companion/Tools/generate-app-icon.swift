import AppKit
import CoreGraphics

// A code-drawn eye and pulse mark; opaque so iOS can apply its own icon mask.
let size = 1024
let space = CGColorSpaceCreateDeviceRGB()
let context = CGContext(data: nil, width: size, height: size,
    bitsPerComponent: 8, bytesPerRow: size * 4, space: space,
    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
context.setFillColor(CGColor(red: 0.055, green: 0.20, blue: 0.19, alpha: 1))
context.fill(CGRect(x: 0, y: 0, width: size, height: size))
context.setLineCap(.round)
context.setLineJoin(.round)
context.setStrokeColor(CGColor(red: 0.57, green: 0.88, blue: 0.72, alpha: 1))
context.setLineWidth(54)
let eye = CGMutablePath()
eye.move(to: CGPoint(x: 166, y: 576))
eye.addCurve(to: CGPoint(x: 858, y: 576),
    control1: CGPoint(x: 350, y: 844), control2: CGPoint(x: 674, y: 844))
eye.addCurve(to: CGPoint(x: 166, y: 576),
    control1: CGPoint(x: 674, y: 308), control2: CGPoint(x: 350, y: 308))
context.addPath(eye)
context.strokePath()
context.setStrokeColor(CGColor(red: 0.96, green: 0.98, blue: 0.95, alpha: 1))
context.setLineWidth(48)
context.strokeEllipse(in: CGRect(x: 414, y: 478, width: 196, height: 196))
context.setLineWidth(38)
context.move(to: CGPoint(x: 264, y: 250))
for point in [CGPoint(x: 402, y: 250), CGPoint(x: 446, y: 310),
    CGPoint(x: 506, y: 184), CGPoint(x: 561, y: 250), CGPoint(x: 760, y: 250)] {
    context.addLine(to: point)
}
context.strokePath()
let bitmap = NSBitmapImageRep(cgImage: context.makeImage()!)
try bitmap.representation(using: .png, properties: [:])!
    .write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
