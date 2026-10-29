using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Linq;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace Protocol.Tests;

[Trait("Category", "Unit")]
public class CoreTests
{
    [Theory]
    [InlineData("01")][InlineData("NaN")][InlineData("[1,]")][InlineData("{\"x\":1,\"x\":2}")][InlineData("\"\\ud800\"")][InlineData("true false")]
    public void RejectsInvalidJson(string json) => Assert.Throws<ProtocolException>(() => Parse(json));
    [Fact] public void PreservesNumbersAndOrder() { const string json = "{\"b\":1e+2,\"a\":[null,true]}"; Assert.Equal(json, Encoding.UTF8.GetString(StrictJson.Serialize(Parse(json)))); }
    [Fact] public void RejectsInvalidUtf8() => Assert.Throws<ProtocolException>(() => StrictJson.Parse(new byte[] { 0xc0, 0x80 }, 0, 2));
    [Fact] public async Task FramesRoundTrip() { using var stream = new MemoryStream(); await FrameCodec.WriteFrameAsync(stream, new byte[] { 1, 2, 3 }, CancellationToken.None); stream.Position = 0; Assert.Equal(new byte[] { 1, 2, 3 }, await FrameCodec.ReadFrameAsync(stream, CancellationToken.None)); Assert.Null(await FrameCodec.ReadFrameAsync(stream, CancellationToken.None)); }
    [Fact] public async Task RejectsShortFrame() { using var stream = new MemoryStream(new byte[] { 3, 0, 0, 0, 1 }); await Assert.ThrowsAsync<ProtocolException>(() => FrameCodec.ReadFrameAsync(stream, CancellationToken.None)); }
    [Fact] public void EnforcesDepth() { Parse(new string('[', 32) + new string(']', 32)); Assert.Throws<ProtocolException>(() => Parse(new string('[', 33) + new string(']', 33))); }
    [Theory][InlineData("-0.25e-10")][InlineData("123456789012345678901234567890")][InlineData("1E+4")]
    public void PreservesNumberText(string text) => Assert.Equal(text, Assert.IsType<JsonNumberNode>(Parse(text)).RawText);
    [Theory][InlineData("1.")][InlineData("1e")][InlineData("+1")][InlineData("-01")][InlineData("Infinity")][InlineData("\ufeff{}")][InlineData("\"\\udc00\"")]
    public void RejectsMoreInvalidJson(string text) => Assert.Throws<ProtocolException>(() => Parse(text));
    [Fact] public void AcceptsPairedSurrogates() => Assert.Equal("😀", Assert.IsType<JsonStringNode>(Parse("\"\\ud83d\\ude00\"")).Value);
    [Theory][InlineData(0u)][InlineData(1048577u)] public async Task RejectsInvalidFrameLength(uint length) { using var s = new MemoryStream(BitConverter.GetBytes(length)); await Assert.ThrowsAsync<ProtocolException>(() => FrameCodec.ReadFrameAsync(s, CancellationToken.None)); }
    [Fact] public async Task ReadsSplitHeaderAndBody() { using var s = new OneByteStream(new byte[] { 3, 0, 0, 0, 1, 2, 3 }); Assert.Equal(new byte[] { 1, 2, 3 }, await FrameCodec.ReadFrameAsync(s, CancellationToken.None)); }
    [Theory][InlineData(new byte[] { 1 })][InlineData(new byte[] { 1, 0, 0 })] public async Task RejectsPartialHeader(byte[] data) { using var s = new OneByteStream(data); await Assert.ThrowsAsync<ProtocolException>(() => FrameCodec.ReadFrameAsync(s, CancellationToken.None)); }
    private sealed class OneByteStream : MemoryStream { public OneByteStream(byte[] data) : base(data) { } public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) => base.ReadAsync(buffer, offset, Math.Min(1, count), cancellationToken); }
    private static JsonNode Parse(string text) { byte[] bytes = Encoding.UTF8.GetBytes(text); return StrictJson.Parse(bytes, 0, bytes.Length); }
}
