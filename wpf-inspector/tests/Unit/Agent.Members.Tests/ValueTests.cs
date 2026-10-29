using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Controls;
using System.Windows.Threading;
using Microsoft.Win32.SafeHandles;
using WinTestKit.Inspector.Protocol;
using Xunit;
using static WinTestKit.Inspector.Agent.Members.Tests.ValueTestSupport;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    [Trait("Category", "Unit")]
    public sealed class ValueTests
    {
        private sealed class Holder
        {
            public object? Value { get; set; }
        }

        private sealed class Scalars
        {
            public string Label => "label";
            public char Letter => 'z';
            public bool Enabled => true;
            public sbyte SignedByte => -8;
            public byte Byte => 8;
            public short Short => -16;
            public ushort UnsignedShort => 16;
            public int Integer => -32;
            public uint UnsignedInteger = 32;
            public long Long = -64;
            public ulong UnsignedLong = 64;
            public float Single = 1.25f;
            public double Double = -2.5;
        }

        [Flags]
        private enum Permissions : ulong { None = 0, Read = 1, Write = 2, High = 1UL << 63 }

        [Fact]
        public void ReadsThirteenUnrelatedPropertiesAndFields()
        {
            Sta(() =>
            {
                var reader = new Reader(new Scalars());
                Assert.Equal("label", Text(reader.Read(Property("Label"))));
                Assert.Equal("z", Text(reader.Read(Property("Letter"))));
                Assert.True(Assert.IsType<JsonBoolNode>(reader.Read(Property("Enabled")).Scalar).Value);
                foreach (var item in new[] { ("SignedByte", "-8"), ("Byte", "8"), ("Short", "-16"), ("UnsignedShort", "16"), ("Integer", "-32") })
                    Assert.Equal(item.Item2, Number(reader.Read(Property(item.Item1))));
                foreach (var item in new[] { ("UnsignedInteger", "32"), ("Long", "-64"), ("UnsignedLong", "64"), ("Single", "1.25"), ("Double", "-2.5") })
                    Assert.Equal(item.Item2, Number(reader.Read(Field(item.Item1))));
                Assert.Equal(0, reader.Registry.Count);
            });
        }

        [Theory]
        [InlineData(9007199254740991L, true)]
        [InlineData(-9007199254740991L, true)]
        [InlineData(9007199254740992L, false)]
        [InlineData(-9007199254740992L, false)]
        [InlineData(long.MinValue, false)]
        [InlineData(long.MaxValue, false)]
        public void SignedIntegersRespectSafeNumberBoundary(long number, bool safe)
        {
            Sta(() => AssertInteger(number, safe));
        }

        [Fact]
        public void UnsignedIntegersRespectSafeNumberBoundary()
        {
            Sta(() =>
            {
                AssertInteger(9007199254740991UL, true);
                AssertInteger(9007199254740992UL, false);
                AssertInteger(ulong.MaxValue, false);
            });
        }

        private static void AssertInteger(object number, bool safe)
        {
            ValueDto value = new Reader(new Holder { Value = number }).Read(Property("Value"));
            string expected = Convert.ToString(number, CultureInfo.InvariantCulture)!;
            Assert.Equal(ValueKind.Integer, value.Kind);
            Assert.Equal(number.GetType().FullName, value.RuntimeType);
            Assert.Equal(typeof(object).FullName, value.DeclaredType);
            if (safe) { Assert.Equal(expected, Number(value)); Assert.Null(value.NumericValue); }
            else { Assert.Equal(expected, Text(value)); Assert.Equal(expected, value.NumericValue); }
        }

        [Fact]
        public void DecimalAndRoundTripTypesAreCultureIndependent()
        {
            Sta(() =>
            {
                CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("fr-FR");
                object[] values = { 12345678901234567890.123456789m, new DateTime(2020, 2, 3, 4, 5, 6, DateTimeKind.Utc).AddTicks(1234), new DateTimeOffset(2020, 2, 3, 4, 5, 6, TimeSpan.FromHours(5.5)).AddTicks(1234), TimeSpan.FromTicks(-1234567890123), new Guid("12345678-1234-5678-9abc-123456789abc") };
                string[] expected = { "12345678901234567890.123456789", "2020-02-03T04:05:06.0001234Z", "2020-02-03T04:05:06.0001234+05:30", "-1.10:17:36.7890123", "12345678-1234-5678-9abc-123456789abc" };
                for (int index = 0; index < values.Length; index++)
                {
                    ValueDto value = new Reader(new Holder { Value = values[index] }).Read(Property("Value"));
                    Assert.Equal(expected[index], Text(value));
                    Assert.Equal(values[index].GetType().FullName, value.RuntimeType);
                    Assert.Equal(index == 0 ? ValueKind.Number : ValueKind.String, value.Kind);
                }
            });
        }

        [Theory]
        [InlineData(double.NaN, "NaN")]
        [InlineData(double.PositiveInfinity, "Infinity")]
        [InlineData(double.NegativeInfinity, "-Infinity")]
        public void NonFiniteNumbersUseExplicitStrings(double number, string expected)
        {
            Sta(() =>
            {
                foreach (object input in new object[] { number, (float)number })
                {
                    ValueDto value = new Reader(new Holder { Value = input }).Read(Property("Value"));
                    Assert.Equal(ValueKind.Number, value.Kind);
                    Assert.Equal(expected, Text(value));
                }
            });
        }

        [Fact]
        public void EnumsKeepNamesFlagsAndUnderlyingNumbers()
        {
            Sta(() =>
            {
                object[] values = { DayOfWeek.Friday, Permissions.Read | Permissions.Write, Permissions.High, (DayOfWeek)(-1), (Permissions)4 };
                string[] names = { "Friday", "Read, Write", "High", "-1", "4" };
                string[] numbers = { "5", "3", "9223372036854775808", "-1", "4" };
                for (int index = 0; index < values.Length; index++)
                {
                    ValueDto value = new Reader(new Holder { Value = values[index] }).Read(Property("Value"));
                    Assert.Equal(ValueKind.Enum, value.Kind);
                    Assert.Equal(names[index], Text(value));
                    Assert.Equal(numbers[index], value.NumericValue);
                }
            });
        }

        [Fact]
        public void TypeValuesContainMetadataWithoutAHandle()
        {
            Sta(() =>
            {
                var reader = new Reader(new Holder { Value = typeof(Scalars) });
                ValueDto value = reader.Read(Property("Value"));
                Assert.Equal(ValueKind.Type, value.Kind);
                Assert.Equal(typeof(Scalars).FullName, value.TypeInfo!.FullName);
                Assert.Null(value.Scalar);
                Assert.Null(value.Object);
                Assert.Equal(0, reader.Registry.Count);
            });
        }

        [Fact]
        public void ArraysExposeOnlyRankAndTotalLength()
        {
            Sta(() =>
            {
                foreach (Array array in new Array[] { new int[0], new object[3], new object[2, 3], Array.CreateInstance(typeof(int), new[] { 2, 3 }, new[] { -1, 5 }) })
                {
                    ValueDto value = new Reader(new Holder { Value = array }).Read(Property("Value"));
                    Assert.Equal(ValueKind.Array, value.Kind);
                    Assert.Equal(array.Rank, value.ArrayRank);
                    Assert.Equal(array.LongLength, value.ArrayLength);
                    Assert.NotNull(value.Object);
                    Assert.Null(value.Scalar);
                }
            });
        }

        private sealed class CollectionProbe : ICollection
        {
            public int Calls;
            public int Count { get { Calls++; throw new InvalidOperationException(); } }
            public bool IsSynchronized { get { Calls++; throw new InvalidOperationException(); } }
            public object SyncRoot { get { Calls++; throw new InvalidOperationException(); } }
            public void CopyTo(Array array, int index) { Calls++; throw new InvalidOperationException(); }
            public IEnumerator GetEnumerator() { Calls++; throw new InvalidOperationException(); }
        }

        private sealed class Hostile
        {
            public int Calls;
            public override string ToString() { Calls++; throw new InvalidOperationException(); }
            public override bool Equals(object? other) { Calls++; throw new InvalidOperationException(); }
            public override int GetHashCode() { Calls++; throw new InvalidOperationException(); }
        }

        private sealed class ListProbe : List<Hostile>, ICollection, IEnumerable
        {
            public int Calls;
            int ICollection.Count { get { Calls++; throw new InvalidOperationException(); } }
            IEnumerator IEnumerable.GetEnumerator() { Calls++; throw new InvalidOperationException(); }
            public override string ToString() { Calls++; throw new InvalidOperationException(); }
        }

        private sealed class DictionaryProbe : Dictionary<string, Hostile>, ICollection, IEnumerable
        {
            public int Calls;
            int ICollection.Count { get { Calls++; throw new InvalidOperationException(); } }
            IEnumerator IEnumerable.GetEnumerator() { Calls++; throw new InvalidOperationException(); }
            public override string ToString() { Calls++; throw new InvalidOperationException(); }
        }

        [Fact]
        public void CollectionsTasksLazyStreamsAndDelegatesRemainUnevaluatedReferences()
        {
            Sta(() =>
            {
                int calls = 0;
                var collection = new CollectionProbe();
                var hostile = new Hostile();
                var list = new ListProbe { hostile };
                var dictionary = new DictionaryProbe { { "entry", hostile } };
                var completion = new TaskCompletionSource<int>();
                var lazy = new Lazy<int>(() => { calls++; return 1; });
                Action callback = () => calls++;
                using (var stream = new MemoryStream())
                {
                    foreach (object input in new object[] { list, dictionary, completion.Task, lazy, callback, stream, collection, hostile })
                    {
                        ValueDto value = new Reader(new Holder { Value = input }).Read(Property("Value"));
                        Assert.Equal(ValueKind.Object, value.Kind);
                        Assert.NotNull(value.Object);
                        Assert.Null(value.Scalar);
                        Assert.Null(value.ArrayLength);
                    }
                    Assert.Equal(0, stream.Position);
                }
                Assert.Equal(0, collection.Calls);
                Assert.Equal(0, list.Calls);
                Assert.Equal(0, dictionary.Calls);
                Assert.Equal(0, hostile.Calls);
                Assert.Equal(0, calls);
                Assert.False(lazy.IsValueCreated);
                Assert.False(completion.Task.IsCompleted);
            });
        }

        [Theory]
        [InlineData(4095, 0, false)]
        [InlineData(4095, 1, false)]
        [InlineData(4095, 2, true)]
        [InlineData(4096, 1, true)]
        [InlineData(0, 4097, true)]
        public void UnicodeTruncationNeverSplitsSurrogatePairs(int asciiCount, int pairCount, bool truncated)
        {
            Sta(() =>
            {
                string input = new string('a', asciiCount) + string.Concat(Enumerable.Repeat("\U0001F600", pairCount));
                ValueDto value = new Reader(new Holder { Value = input }).Read(Property("Value"));
                string expected = new string('a', Math.Min(asciiCount, 4096)) + string.Concat(Enumerable.Repeat("\U0001F600", Math.Min(pairCount, Math.Max(0, 4096 - asciiCount))));
                Assert.Equal(expected, Text(value));
                Assert.Equal(truncated ? ValueStatus.Truncated : ValueStatus.Ok, value.Status);
                Assert.Equal(truncated ? (long?)(asciiCount + pairCount) : null, value.TruncatedAt);
            });
        }

        private sealed class Node
        {
            public int Calls;
            public Node? ChildValue;
            public Node? Child { get { Calls++; return ChildValue; } }
            public int Number { get { Calls++; return 42; } }
            public int Fail => throw new InvalidOperationException("DO NOT EXPORT THIS MESSAGE");
        }

        [Fact]
        public void UnpairedSurrogatesAreUnsupportedRatherThanInvalidWireValues()
        {
            Sta(() =>
            {
                foreach (object input in new object[] { new string((char)0xd800, 1), new string((char)0xdc00, 1), (char)0xd800, "valid" + (char)0xd800 })
                {
                    ValueDto value = new Reader(new Holder { Value = input }).Read(Property("Value"));
                    Assert.Equal(ValueStatus.Unsupported, value.Status);
                    Assert.Null(value.Scalar);
                    Assert.Null(value.Object);
                }
            });
        }

        private sealed class ExceptionProbe : Exception
        {
            public int Calls;
            public override string Message { get { Calls++; throw new InvalidOperationException(); } }
            public override string? StackTrace { get { Calls++; throw new InvalidOperationException(); } }
        }

        private sealed class Throwing
        {
            public ExceptionProbe Error = new ExceptionProbe();
            public int Value => throw Error;
        }

        [Fact]
        public void ExceptionReportingNeverReadsMessageOrStackTrace()
        {
            Sta(() =>
            {
                var target = new Throwing();
                ValueDto value = new Reader(target).Read(Property("Value"));
                Assert.Equal(ValueStatus.Exception, value.Status);
                Assert.Equal(typeof(ExceptionProbe).FullName, value.Message);
                Assert.Equal(0, value.FailedSegment);
                Assert.Equal(0, target.Error.Calls);
            });
        }

        [Fact]
        public void NullAndExceptionsReportTheProducingSegment()
        {
            Sta(() =>
            {
                var child = new Node();
                var reader = new Reader(new Node { ChildValue = child });
                ValueDto final = reader.Read(Property("Child"), Property("Child"));
                Assert.Equal(ValueStatus.Ok, final.Status);
                Assert.Equal(ValueKind.Null, final.Kind);
                Assert.IsType<JsonNullNode>(final.Scalar);
                ValueDto missing = reader.Read(Property("Child"), Property("Child"), Property("Number"));
                Assert.Equal(ValueStatus.NullIntermediate, missing.Status);
                Assert.Equal(1, missing.FailedSegment);
                ValueDto failure = reader.Read(Property("Child"), Property("Fail"));
                Assert.Equal(ValueStatus.Exception, failure.Status);
                Assert.Equal(1, failure.FailedSegment);
                Assert.Equal(typeof(InvalidOperationException).FullName, failure.Message);
                Assert.Null(failure.Scalar);
                Assert.Null(failure.Object);
            });
        }

        [Fact]
        public void EachSegmentIsReadExactlyOnceAndNoResultsAreCached()
        {
            Sta(() =>
            {
                var child = new Node();
                var root = new Node { ChildValue = child };
                var reader = new Reader(root);
                Assert.Equal("42", Number(reader.Read(Property("Child"), Property("Number"))));
                Assert.Equal(1, root.Calls);
                Assert.Equal(1, child.Calls);
                reader.Read(Property("Child"), Property("Number"));
                Assert.Equal(2, root.Calls);
                Assert.Equal(2, child.Calls);
            });
        }

        [Fact]
        public void CyclesUseReferenceIdentityAndSharedValuesReuseHandles()
        {
            Sta(() =>
            {
                var root = new Node();
                var child = new Node { ChildValue = root };
                root.ChildValue = child;
                var reader = new Reader(root);
                ValueDto first = reader.Read(Property("Child"));
                ValueDto second = reader.Read(Field("ChildValue"));
                Assert.Equal(first.Object!.ObjectId, second.Object!.ObjectId);
                ValueDto cycle = reader.Read(Property("Child"), Property("Child"));
                Assert.Equal(ValueStatus.Cycle, cycle.Status);
                Assert.Equal(reader.Registry.Register(root, Dispatcher.CurrentDispatcher, reader.Inspector.DescribeType(typeof(Node))).ObjectId, cycle.CycleTo!.ObjectId);
                Assert.Null(cycle.Object);
                child.ChildValue = child;
                ValueDto selfCycle = reader.Read(Property("Child"), Property("Child"), Property("Number"));
                Assert.Equal(ValueStatus.Cycle, selfCycle.Status);
                Assert.Equal(first.Object.ObjectId, selfCycle.CycleTo!.ObjectId);
                var hostile = new Hostile();
                var hostileReader = new Reader(new Holder { Value = hostile });
                Assert.Equal(hostileReader.Read(Property("Value")).Object!.ObjectId, hostileReader.Read(Property("Value")).Object!.ObjectId);
                Assert.Equal(0, hostile.Calls);
            });
        }

        private sealed class Sensitive
        {
            public int Calls;
            private string Read() { Calls++; return "must not escape"; }
            public string PASSWORD => Read();
            public string PasswdHint => Read();
            public string DbPwd => Read();
            public string ClientSecret => Read();
            public CancellationToken CancellationToken { get { Calls++; return CancellationToken.None; } }
            public string Credential => Read();
            public string ConnectionString => Read();
            public string ApiKey => Read();
            public string PrivateKey => Read();
            public string Additional => Read();
            public Sensitive Child { get { Calls++; return this; } }
        }

        [Theory]
        [InlineData("PASSWORD", "password")]
        [InlineData("PasswdHint", "passwd")]
        [InlineData("DbPwd", "pwd")]
        [InlineData("ClientSecret", "secret")]
        [InlineData("CancellationToken", "token")]
        [InlineData("Credential", "credential")]
        [InlineData("ConnectionString", "connectionstring")]
        [InlineData("ApiKey", "apikey")]
        [InlineData("PrivateKey", "privatekey")]
        [InlineData("Additional", "ADDITIONAL")]
        public void RedactsTheEntirePathBeforeAnyGetterOrHandle(string name, string rule)
        {
            Sta(() =>
            {
                var target = new Sensitive();
                var reader = new Reader(target, "ADDITIONAL");
                foreach (PathSegment[] path in new[] { new[] { Property(name) }, new[] { Property("Child"), Property(name) } })
                {
                    ValueDto value = reader.Read(path);
                    Assert.Equal(ValueStatus.Redacted, value.Status);
                    Assert.Equal(rule, value.RedactionRule);
                    Assert.Null(value.Scalar);
                    Assert.Null(value.Object);
                }
                Assert.Equal(0, target.Calls);
                Assert.Equal(0, reader.Registry.Count);
            });
        }

        [Fact]
        public void PasswordBoxUsesDeclaringTypeIdentity()
        {
            Sta(() =>
            {
                var reader = new Reader(new PasswordBox());
                foreach (string name in new[] { "Password", "SecurePassword" })
                {
                    ValueDto value = reader.Read(Property(name));
                    Assert.Equal(ValueStatus.Redacted, value.Status);
                    Assert.Equal("identity", value.RedactionRule);
                }
                Assert.Equal(0, reader.Registry.Count);
            });
        }

        private class BaseHidden { public int Same => 1; }
        private sealed class Hidden : BaseHidden { public new int Same => 2; public int Other => 3; }

        [Fact]
        public void HiddenNamesRequireQualificationOrAnAgreeingMemberKey()
        {
            Sta(() =>
            {
                var reader = new Reader(new Hidden());
                Assert.Equal(ErrorCodes.MemberAmbiguous, Assert.Throws<ProtocolException>(() => reader.Read(Property("Same"))).Code);
                var members = reader.Inspector.GetMembers(new Hidden(), new List<Diagnostic>()).Where(member => member.Name == "Same").ToArray();
                Assert.Equal(2, members.Length);
                foreach (var member in members)
                {
                    Assert.Equal(member.DeclaringType == typeof(Hidden).FullName ? "2" : "1", Number(reader.Read(member.PathSegment!)));
                    Assert.Equal(member.DeclaringType == typeof(Hidden).FullName ? "2" : "1", Number(reader.Read(new PathSegment { Kind = SegmentKind.Property, Name = "Same", MemberKey = member.MemberKey })));
                }
                string key = members[0].MemberKey;
                foreach (var segment in new[] { new PathSegment { Kind = SegmentKind.Property, Name = "Other", MemberKey = key }, new PathSegment { Kind = SegmentKind.Field, Name = "Same", MemberKey = key }, new PathSegment { Kind = SegmentKind.Property, Name = "Same", MemberKey = "missing" }, new PathSegment { Kind = SegmentKind.Property, Name = "Same", DeclaringType = typeof(string).FullName } })
                    Assert.Equal(ErrorCodes.MemberNotFound, Assert.Throws<ProtocolException>(() => reader.Read(segment)).Code);
            });
        }

        [Fact]
        public void TypeSegmentsAreSoleMetadataOnlyReads()
        {
            Sta(() =>
            {
                var target = new Sensitive();
                var reader = new Reader(target);
                foreach (string name in new[] { "Name", "FullName", "AssemblyName", "AssemblyQualifiedName", "BaseTypes" })
                {
                    ValueDto value = reader.Read(new PathSegment { Kind = SegmentKind.Type, Name = name });
                    Assert.Equal(ValueStatus.Ok, value.Status);
                    if (name == "FullName") Assert.Equal(typeof(Sensitive).FullName, Text(value));
                    if (name == "BaseTypes") { Assert.Equal(ValueKind.Array, value.Kind); Assert.Equal(typeof(string[]).FullName, value.DeclaredType); }
                }
                foreach (PathSegment[] path in new[] { new[] { Property("Child"), new PathSegment { Kind = SegmentKind.Type, Name = "FullName" } }, new[] { new PathSegment { Kind = SegmentKind.Type, Name = "Name" }, Property("Child") } })
                    Assert.Equal(ErrorCodes.InvalidParams, Assert.Throws<ProtocolException>(() => reader.Read(path)).Code);
                Assert.Equal(0, target.Calls);
            });
        }

        [Fact]
        public void UnsafeRuntimeValuesAreUnavailableAndNeverRegistered()
        {
            Sta(() =>
            {
                using (var secure = new SecureString())
                using (var handle = new SafeFileHandle(IntPtr.Zero, false))
                {
                    foreach (object input in new object[] { secure, handle, IntPtr.Zero, UIntPtr.Zero, new InvalidOperationException("hidden"), Dispatcher.CurrentDispatcher, Dispatcher.CurrentDispatcher.Hooks })
                    {
                        var reader = new Reader(new Holder { Value = input });
                        ValueDto value = reader.Read(Property("Value"));
                        Assert.Equal(ValueStatus.Unsupported, value.Status);
                        Assert.Equal(ValueKind.Unavailable, value.Kind);
                        Assert.Null(value.Object);
                        Assert.Null(value.Scalar);
                        Assert.Equal(0, reader.Registry.Count);
                    }
                }
            });
        }

        internal static string Text(ValueDto value) => Assert.IsType<JsonStringNode>(value.Scalar).Value;
        internal static string Number(ValueDto value) => Assert.IsType<JsonNumberNode>(value.Scalar).RawText;
    }
}
