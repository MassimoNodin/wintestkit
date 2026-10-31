using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;
using MemberInfo = WinTestKit.Inspector.Protocol.MemberInfo;

[assembly: CollectionBehavior(DisableTestParallelization = true)]

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    [Trait("Category", "Unit")]
    public sealed class CatalogTests
    {
        private static int getterCalls;
        private static int attributeCalls;
        private static int staticCalls;
        private static readonly string[] TypeKeys = { "type:Name", "type:FullName", "type:AssemblyName", "type:AssemblyQualifiedName", "type:BaseTypes" };

        [AttributeUsage(AttributeTargets.All, AllowMultiple = true, Inherited = true)]
        private sealed class ProbeAttribute : Attribute
        {
            public ProbeAttribute(string text, bool flag, int number, double fraction, DayOfWeek day, Type type, int[] values, string? empty)
            { attributeCalls++; }
            public string Label { get { getterCalls++; return ""; } set { } }
        }

        private sealed class Unrelated
        {
            static Unrelated() { staticCalls++; }
            public static int Value => 1;
        }

        private class ModelBase
        {
            [Probe("base", true, 7, 1.25, DayOfWeek.Monday, typeof(string), new[] { 1, 2 }, null, Label = "named")]
            public virtual int Virtual { get { getterCalls++; return 1; } }
            public int Hidden { get { getterCalls++; return 1; } }
            private int Secret { get { getterCalls++; return 1; } }
            protected int Protected { get { getterCalls++; return 1; } }
            internal int Internal { get { getterCalls++; return 1; } }
            protected internal int ProtectedInternal { get { getterCalls++; return 1; } }
            private protected int PrivateProtected { get { getterCalls++; return 1; } }
            public int Field = 1;
            private int privateField = 1;
            public int KeepField() => privateField;
        }

        [Probe("type", false, 0, 0.5, DayOfWeek.Tuesday, typeof(int), new int[0], null)]
        private sealed class Model : ModelBase
        {
            [Browsable(false)]
            public override int Virtual { get { getterCalls++; return 2; } }
            public new int Hidden { get { getterCalls++; return 2; } }
            public int WriteOnly { set { } }
            public int PrivateGetter { private get { getterCalls++; return 1; } set { } }
            public int this[int index] { get { getterCalls++; return index; } }
            public int this[string index] { get { getterCalls++; return index.Length; } }
            public ref int ByReference => ref Field;
#if !NET48
            public Span<int> ByRefLike { get { getterCalls++; return default; } }
#endif
            public Unrelated? Uninitialized { get { getterCalls++; return null; } }
            public static int Static { get { getterCalls++; return 1; } }
        }

        private sealed class DynamicModel
        {
            public int Existing { get { getterCalls++; return 1; } }
            [Browsable(false)]
            public int Invisible { get { getterCalls++; return 1; } }
        }

        private sealed class DynamicProperty : PropertyDescriptor
        {
            private readonly Type component;
            private readonly Type valueType;
            private readonly bool fail;
            internal DynamicProperty(string name, Type component, Type valueType, bool fail = false) : base(name, new Attribute[0])
            { this.component = component; this.valueType = valueType; this.fail = fail; }
            public override Type ComponentType => component;
            public override Type PropertyType => fail ? throw new InvalidOperationException("not for diagnostics") : valueType;
            public override bool IsReadOnly => true;
            public override bool CanResetValue(object component) => false;
            public override object GetValue(object? component) { getterCalls++; throw new InvalidOperationException(); }
            public override void ResetValue(object component) => throw new NotSupportedException();
            public override void SetValue(object? component, object? value) => throw new NotSupportedException();
            public override bool ShouldSerializeValue(object component) => false;
        }

        private sealed class Provider : TypeDescriptionProvider
        {
            private readonly TypeDescriptionProvider parent;
            private readonly PropertyDescriptor[] extras;
            private readonly bool fail;
            internal Provider(Type type, PropertyDescriptor[] extras, bool fail = false)
            { parent = TypeDescriptor.GetProvider(type); this.extras = extras; this.fail = fail; }
            public override ICustomTypeDescriptor GetTypeDescriptor(Type objectType, object? instance)
                => new Description(parent.GetTypeDescriptor(objectType, instance)!, extras, fail);
        }

        private sealed class Description : CustomTypeDescriptor
        {
            private readonly PropertyDescriptor[] extras;
            private readonly bool fail;
            internal Description(ICustomTypeDescriptor parent, PropertyDescriptor[] extras, bool fail) : base(parent)
            { this.extras = extras; this.fail = fail; }
            public override PropertyDescriptorCollection GetProperties()
                => fail ? throw new InvalidOperationException("not for diagnostics") : new PropertyDescriptorCollection(base.GetProperties().Cast<PropertyDescriptor>().Concat(extras).ToArray());
            public override PropertyDescriptorCollection GetProperties(Attribute[]? attributes) => GetProperties();
        }

        private sealed class ControlFixture : FrameworkElement
        {
            public static readonly DependencyProperty DefaultProperty = DependencyProperty.Register(nameof(Default), typeof(int), typeof(ControlFixture), new FrameworkPropertyMetadata(4, FrameworkPropertyMetadataOptions.AffectsMeasure | FrameworkPropertyMetadataOptions.AffectsArrange | FrameworkPropertyMetadataOptions.AffectsRender | FrameworkPropertyMetadataOptions.BindsTwoWayByDefault));
            public static readonly DependencyProperty LocalProperty = DependencyProperty.Register(nameof(Local), typeof(int), typeof(ControlFixture), new PropertyMetadata(0));
            public static readonly DependencyProperty BoundProperty = DependencyProperty.Register(nameof(Bound), typeof(int), typeof(ControlFixture), new PropertyMetadata(0));
            public int Default { get { getterCalls++; return (int)GetValue(DefaultProperty); } set { SetValue(DefaultProperty, value); } }
            public int Local { get { getterCalls++; return (int)GetValue(LocalProperty); } set { SetValue(LocalProperty, value); } }
            public int Bound { get { getterCalls++; return (int)GetValue(BoundProperty); } set { SetValue(BoundProperty, value); } }
        }

        public static class AttachedOwner
        {
            public static readonly DependencyProperty TagProperty = DependencyProperty.RegisterAttached("Tag", typeof(string), typeof(AttachedOwner), new FrameworkPropertyMetadata("", FrameworkPropertyMetadataOptions.Inherits));
            public static readonly DependencyProperty LocalProperty = DependencyProperty.RegisterAttached("Local", typeof(int), typeof(AttachedOwner), new PropertyMetadata(0));
            public static string GetTag(DependencyObject target) { getterCalls++; return (string)target.GetValue(TagProperty); }
            public static void SetTag(DependencyObject target, string value) => target.SetValue(TagProperty, value);
            public static int GetLocal(DependencyObject target) { getterCalls++; return (int)target.GetValue(LocalProperty); }
            public static void SetLocal(DependencyObject target, int value) => target.SetValue(LocalProperty, value);
        }

        private sealed class MetadataFixture : DependencyObject
        {
            internal static readonly DependencyPropertyKey FrozenKey = DependencyProperty.RegisterReadOnly("Frozen", typeof(int), typeof(MetadataFixture), new PropertyMetadata(0));
            internal static readonly DependencyProperty FlagsProperty = DependencyProperty.Register("Flags", typeof(int), typeof(MetadataFixture), new FrameworkPropertyMetadata(0, FrameworkPropertyMetadataOptions.AffectsMeasure | FrameworkPropertyMetadataOptions.AffectsArrange | FrameworkPropertyMetadataOptions.AffectsParentMeasure | FrameworkPropertyMetadataOptions.AffectsParentArrange | FrameworkPropertyMetadataOptions.AffectsRender | FrameworkPropertyMetadataOptions.Inherits | FrameworkPropertyMetadataOptions.OverridesInheritanceBehavior | FrameworkPropertyMetadataOptions.NotDataBindable | FrameworkPropertyMetadataOptions.BindsTwoWayByDefault | FrameworkPropertyMetadataOptions.Journal | FrameworkPropertyMetadataOptions.SubPropertiesDoNotAffectRender));
        }

        private sealed class NamelessType : TypeDelegator
        {
            internal NamelessType() : base(typeof(Model)) { }
            public override string? FullName => null;
            public override string? AssemblyQualifiedName => null;
            public override string ToString() => throw new InvalidOperationException("No ToString fallback");
        }

        private static void Sta(Action action)
        {
            Exception? failure = null;
            var thread = new Thread(() =>
            {
                Dispatcher dispatcher = Dispatcher.CurrentDispatcher;
                dispatcher.BeginInvoke(new Action(() =>
                {
                    try { action(); }
                    catch (Exception exception) { failure = exception; }
                    finally { dispatcher.BeginInvokeShutdown(DispatcherPriority.Background); }
                }));
                Dispatcher.Run();
            });
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
            Assert.True(thread.Join(TimeSpan.FromSeconds(30)), "STA Dispatcher did not complete.");
            if (failure != null) ExceptionDispatchInfo.Capture(failure).Throw();
        }

        private static string Property(Type type, string name, string parameters = "") => "clrProperty|" + type.Assembly.GetName().Name + "|" + type.FullName + "|" + name + "|" + parameters;
        private static string Field(Type type, string name) => "clrField|" + type.Assembly.GetName().Name + "|" + type.FullName + "|" + name;
        private static string Descriptor(Type component, string name, Type valueType) => "descriptorProperty|" + component.Assembly.GetName().Name + "|" + component.FullName + "|" + name + "|" + valueType.FullName;
        private static string Dependency(DependencyProperty property) => "dependencyProperty|" + property.OwnerType.Assembly.GetName().Name + "|" + property.OwnerType.FullName + "|" + property.Name;
        private static string Text(JsonNode node) => Assert.IsType<JsonStringNode>(node).Value;

        private static IReadOnlyList<MemberInfo> Catalog(object target, out List<Diagnostic> diagnostics)
        {
            diagnostics = new List<Diagnostic>();
            IReadOnlyList<MemberInfo> members = new ObjectInspector().GetMembers(target, diagnostics);
            foreach (MemberInfo member in members)
            {
                byte[] bytes = StrictJson.Serialize(member.ToJson());
                MemberInfo copy = MemberInfo.FromJson(StrictJson.Parse(bytes, 0, bytes.Length));
                Assert.Equal(bytes, StrictJson.Serialize(copy.ToJson()));
            }
            Assert.Equal(members.Count, members.Select(member => member.MemberKey).Distinct(StringComparer.Ordinal).Count());
            return members;
        }

        private static void ExactKeys(IEnumerable<string> expected, IReadOnlyList<MemberInfo> actual)
            => Assert.Equal(expected.OrderBy(key => key, StringComparer.Ordinal).ToArray(), actual.Select(member => member.MemberKey).OrderBy(key => key, StringComparer.Ordinal).ToArray());

        private static string[] ModelKeys()
        {
            var keys = new List<string>(TypeKeys);
            keys.AddRange(new[] { "Virtual", "Hidden", "WriteOnly", "PrivateGetter", "ByReference", "Uninitialized" }.Select(name => Property(typeof(Model), name)));
#if !NET48
            keys.Add(Property(typeof(Model), "ByRefLike"));
#endif
            keys.Add(Property(typeof(Model), "Item", "System.Int32"));
            keys.Add(Property(typeof(Model), "Item", "System.String"));
            keys.AddRange(new[] { "Hidden", "Secret", "Protected", "Internal", "ProtectedInternal", "PrivateProtected" }.Select(name => Property(typeof(ModelBase), name)));
            keys.Add(Field(typeof(ModelBase), "Field"));
            keys.Add(Field(typeof(ModelBase), "privateField"));
            return keys.ToArray();
        }

        [Fact]
        public void CompleteClrCatalogPreservesDeclarationsWithoutInvokingTargetCode()
        {
            Sta(() =>
            {
                getterCalls = attributeCalls = staticCalls = 0;
                IReadOnlyList<MemberInfo> members = Catalog(new Model(), out _);
                ExactKeys(ModelKeys(), members);
                Assert.Equal(0, getterCalls);
                Assert.Equal(0, attributeCalls);
                Assert.Equal(0, staticCalls);
                Assert.DoesNotContain(members, member => member.Name == "Static");
                MemberInfo overridden = Assert.Single(members, member => member.MemberKey == Property(typeof(Model), "Virtual"));
                Assert.Equal(typeof(Model).FullName, overridden.DeclaringType);
                Assert.Contains(overridden.Attributes, attribute => attribute.TypeName == typeof(ProbeAttribute).FullName);
                Assert.Contains(overridden.Attributes, attribute => attribute.TypeName == typeof(BrowsableAttribute).FullName);
            });
        }

        [Fact]
        public void ReadabilityUsesGetterVisibilityAndRejectsUnsupportedDeclarations()
        {
            Sta(() =>
            {
                IReadOnlyList<MemberInfo> members = Catalog(new Model(), out _);
                void Check(Type type, string name, string visibility, string reason)
                {
                    MemberInfo row = Assert.Single(members, member => member.MemberKey == Property(type, name));
                    Assert.False(row.Readable); Assert.Equal(visibility, row.Visibility); Assert.Equal(reason, row.Reason);
                }
                Check(typeof(Model), "WriteOnly", "public", "writeOnly");
                Check(typeof(Model), "PrivateGetter", "private", "nonPublic");
                Check(typeof(Model), "ByReference", "public", "unsupportedType");
#if !NET48
                Check(typeof(Model), "ByRefLike", "public", "unsupportedType");
#endif
                Check(typeof(ModelBase), "Secret", "private", "nonPublic");
                Check(typeof(ModelBase), "Protected", "protected", "nonPublic");
                Check(typeof(ModelBase), "Internal", "internal", "nonPublic");
                Check(typeof(ModelBase), "ProtectedInternal", "protectedInternal", "nonPublic");
                Check(typeof(ModelBase), "PrivateProtected", "privateProtected", "nonPublic");
                Assert.All(members.Where(member => member.Name == "Item"), member => { Assert.False(member.Readable); Assert.Equal("indexer", member.Reason); });
                Assert.Equal("nonPublic", Assert.Single(members, member => member.MemberKey == Field(typeof(ModelBase), "privateField")).Reason);
            });
        }

        [Fact]
        public void AttributeArgumentsUseStrictTypedLiteralsAndRetainBaseMetadata()
        {
            Sta(() =>
            {
                IReadOnlyList<MemberInfo> members = Catalog(new Model(), out _);
                AttributeInfo attribute = Assert.Single(Assert.Single(members, member => member.MemberKey == Property(typeof(Model), "Virtual")).Attributes, item => item.TypeName == typeof(ProbeAttribute).FullName);
                Assert.Equal(new[] { "string", "boolean", "integer", "number", "enum", "type", "array", "null" }, attribute.ConstructorArguments.Select(item => Text(Assert.IsType<JsonObjectNode>(item).Get("kind"))).ToArray());
                Assert.Equal("base", Text(Assert.IsType<JsonObjectNode>(attribute.ConstructorArguments[0]).Get("value")));
                Assert.Equal("System.DayOfWeek.Monday", Text(Assert.IsType<JsonObjectNode>(attribute.ConstructorArguments[4]).Get("value")));
                Assert.Equal(typeof(string).AssemblyQualifiedName, Text(Assert.IsType<JsonObjectNode>(attribute.ConstructorArguments[5]).Get("value")));
                Assert.Equal(2, Assert.IsType<JsonArrayNode>(Assert.IsType<JsonObjectNode>(attribute.ConstructorArguments[6]).Get("value")).Items.Count);
                Assert.Equal("named", Text(Assert.IsType<JsonObjectNode>(attribute.NamedArguments.Get("Label")).Get("value")));
            });
        }

        [Fact]
        public void CompleteDynamicCatalogMergesIdentityAndMarksDuplicatesAmbiguous()
        {
            Sta(() =>
            {
                var target = new DynamicModel();
                var extras = new[]
                {
                    new DynamicProperty("Existing", typeof(DynamicModel), typeof(int)),
                    new DynamicProperty("Dynamic", typeof(DynamicModel), typeof(string)),
                    new DynamicProperty("Duplicate", typeof(DynamicModel), typeof(int)),
                    new DynamicProperty("Duplicate", typeof(DynamicModel), typeof(int)),
                    new DynamicProperty("Duplicate", typeof(DynamicModel), typeof(string)),
                    new DynamicProperty("Existing", typeof(ModelBase), typeof(int))
                };
                var provider = new Provider(typeof(DynamicModel), extras);
                TypeDescriptor.AddProvider(provider, target);
                try
                {
                    getterCalls = 0;
                    IReadOnlyList<MemberInfo> members = Catalog(target, out List<Diagnostic> diagnostics);
                    ExactKeys(TypeKeys.Concat(new[] { Property(typeof(DynamicModel), "Existing"), Property(typeof(DynamicModel), "Invisible"), Descriptor(typeof(DynamicModel), "Dynamic", typeof(string)), Descriptor(typeof(DynamicModel), "Duplicate", typeof(int)), Descriptor(typeof(DynamicModel), "Duplicate", typeof(string)), Descriptor(typeof(ModelBase), "Existing", typeof(int)) }), members);
                    Assert.Equal("ambiguous", Assert.Single(members, member => member.MemberKey == Property(typeof(DynamicModel), "Existing")).Reason);
                    MemberInfo duplicate = Assert.Single(members, member => member.MemberKey == Descriptor(typeof(DynamicModel), "Duplicate", typeof(int)));
                    Assert.False(duplicate.Readable); Assert.Equal("ambiguous", duplicate.Reason);
                    Assert.True(Assert.Single(members, member => member.MemberKey == Descriptor(typeof(DynamicModel), "Duplicate", typeof(string))).Readable);
                    Assert.Contains(diagnostics, diagnostic => diagnostic.Code == "descriptorAttributesUnavailable");
                    Assert.Equal(0, getterCalls);
                }
                finally { TypeDescriptor.RemoveProvider(provider, target); }
            });
        }

        [Fact]
        public void DynamicDescriptorsArePerInstanceAndPerSnapshot()
        {
            Sta(() =>
            {
                var target = new DynamicModel();
                var provider = new Provider(typeof(DynamicModel), new[] { new DynamicProperty("Extra", typeof(DynamicModel), typeof(int)) });
                TypeDescriptor.AddProvider(provider, target);
                try
                {
                    Assert.Contains(Catalog(target, out _), member => member.Name == "Extra");
                    ExactKeys(TypeKeys.Concat(new[] { Property(typeof(DynamicModel), "Existing"), Property(typeof(DynamicModel), "Invisible") }), Catalog(new DynamicModel(), out _));
                }
                finally { TypeDescriptor.RemoveProvider(provider, target); }
                ExactKeys(TypeKeys.Concat(new[] { Property(typeof(DynamicModel), "Existing"), Property(typeof(DynamicModel), "Invisible") }), Catalog(target, out _));
            });
        }

        private static HashSet<string> FrameworkKeys(ControlFixture target)
        {
            var expected = new HashSet<string>(TypeKeys, StringComparer.Ordinal);
            var properties = new List<PropertyInfo>();
            foreach (string name in new[] { "Default", "Local", "Bound" })
            {
                expected.Add(Property(typeof(ControlFixture), name));
                properties.Add(typeof(ControlFixture).GetProperty(name)!);
            }
            foreach (DependencyProperty property in new[] { ControlFixture.DefaultProperty, ControlFixture.LocalProperty, ControlFixture.BoundProperty, FrameworkElement.DataContextProperty })
                expected.Add(Dependency(property));
            var virtualSlots = new HashSet<MethodInfo>();
            for (Type? current = typeof(FrameworkElement); current != null; current = current.BaseType)
            {
                const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
                foreach (PropertyInfo property in current.GetProperties(flags))
                {
                    MethodInfo? accessor = property.GetGetMethod(true) ?? property.GetSetMethod(true);
                    if (accessor != null && accessor.IsVirtual && !virtualSlots.Add(accessor.GetBaseDefinition())) continue;
                    properties.Add(property);
                    expected.Add(Property(current, property.Name, string.Join(",", property.GetIndexParameters().Select(parameter => parameter.ParameterType.FullName))));
                }
                foreach (FieldInfo field in current.GetFields(flags)) expected.Add(Field(current, field.Name));
            }
            foreach (PropertyDescriptor descriptor in TypeDescriptor.GetProperties(target))
            {
                if (!properties.Any(property => property.DeclaringType == descriptor.ComponentType && property.Name == descriptor.Name && property.PropertyType == descriptor.PropertyType))
                    expected.Add(Descriptor(descriptor.ComponentType, descriptor.Name, descriptor.PropertyType));
                DependencyPropertyDescriptor? dependency = DependencyPropertyDescriptor.FromProperty(descriptor);
                if (dependency != null) expected.Add(Dependency(dependency.DependencyProperty));
            }
            expected.Add(Dependency(AttachedOwner.TagProperty));
            return expected;
        }

        [Fact]
        public void CompleteWpfCatalogUnionsDefaultLocalAttachedInheritedAndBoundProperties()
        {
            Sta(() =>
            {
                var target = new ControlFixture();
                var parent = new Decorator { Child = target, DataContext = "inherited" };
                target.SetValue(ControlFixture.LocalProperty, 3);
                AttachedOwner.SetTag(target, "attached");
                BindingOperations.SetBinding(target, ControlFixture.BoundProperty, new Binding { Source = 17 });
                Assert.Equal(BaseValueSource.Inherited, DependencyPropertyHelper.GetValueSource(target, FrameworkElement.DataContextProperty).BaseValueSource);
                Assert.True(DependencyPropertyHelper.GetValueSource(target, ControlFixture.BoundProperty).IsExpression);
                getterCalls = 0;
                IReadOnlyList<MemberInfo> members = Catalog(target, out _);
                Assert.Equal(0, getterCalls);
                foreach (DependencyProperty property in new[] { ControlFixture.DefaultProperty, ControlFixture.LocalProperty, ControlFixture.BoundProperty, FrameworkElement.DataContextProperty, AttachedOwner.TagProperty })
                    Assert.Single(members, member => member.MemberKey == Dependency(property));
                foreach (string name in new[] { "Default", "Local", "Bound" })
                {
                    MemberInfo wrapper = Assert.Single(members, member => member.MemberKey == Property(typeof(ControlFixture), name));
                    MemberInfo dependency = Assert.Single(members, member => member.MemberKey == wrapper.WrapperKey);
                    Assert.Equal(wrapper.MemberKey, dependency.WrapperKey);
                    Assert.Equal("System.Int32", Text(dependency.Dependency!.Get("propertyType")));
                    Assert.Equal("false", Text(dependency.Dependency.Get("isAttached")));
                }
                MemberInfo defaultRow = Assert.Single(members, member => member.MemberKey == Dependency(ControlFixture.DefaultProperty));
                Assert.False(Assert.IsType<JsonBoolNode>(defaultRow.Dependency!.Get("hasLocalValue")).Value);
                Assert.Equal(new[] { "AffectsMeasure", "AffectsArrange", "AffectsRender", "BindsTwoWayByDefault" }, Assert.IsType<JsonArrayNode>(defaultRow.Dependency.Get("metadataFlags")).Items.Select(Text).ToArray());
                Assert.True(Assert.IsType<JsonBoolNode>(Assert.Single(members, member => member.MemberKey == Dependency(ControlFixture.LocalProperty)).Dependency!.Get("hasLocalValue")).Value);
                MemberInfo attached = Assert.Single(members, member => member.MemberKey == Dependency(AttachedOwner.TagProperty));
                Assert.Null(attached.WrapperKey);
                Assert.Contains(Text(attached.Dependency!.Get("isAttached")), new[] { "true", "unknown" });
                GC.KeepAlive(parent);
            });
        }

        [Fact]
        public void DescriptorFailureIsDiagnosticAndPreservesTypeClrAndLocalDependencyRows()
        {
            Sta(() =>
            {
                var target = new ControlFixture();
                target.SetValue(ControlFixture.LocalProperty, 2);
                var provider = new Provider(typeof(ControlFixture), new PropertyDescriptor[0], true);
                TypeDescriptor.AddProvider(provider, target);
                try
                {
                    IReadOnlyList<MemberInfo> members = Catalog(target, out List<Diagnostic> diagnostics);
                    Assert.Contains(diagnostics, diagnostic => diagnostic.Category == "descriptor" && diagnostic.Code == "discoveryFailed");
                    Assert.Contains(diagnostics, diagnostic => diagnostic.Category == "dependency");
                    Assert.All(diagnostics, diagnostic => Assert.DoesNotContain("not for diagnostics", diagnostic.Message));
                    Assert.Contains(members, member => member.MemberKey == "type:FullName");
                    Assert.Contains(members, member => member.MemberKey == Property(typeof(ControlFixture), "Default"));
                    MemberInfo dependency = Assert.Single(members, member => member.MemberKey == Dependency(ControlFixture.LocalProperty));
                    Assert.Equal("unknown", Text(dependency.Dependency!.Get("isAttached")));
                }
                finally { TypeDescriptor.RemoveProvider(provider, target); }
            });
        }

        [Fact]
        public void DependencyMetadataIncludesEveryClosedFlagAndReadOnlyState()
        {
            Sta(() =>
            {
                var target = new MetadataFixture();
                target.SetValue(MetadataFixture.FrozenKey, 1);
                target.SetValue(MetadataFixture.FlagsProperty, 2);
                IReadOnlyList<MemberInfo> members = Catalog(target, out _);
                MemberInfo frozen = Assert.Single(members, member => member.MemberKey == Dependency(MetadataFixture.FrozenKey.DependencyProperty));
                Assert.True(frozen.Readable);
                Assert.True(Assert.IsType<JsonBoolNode>(frozen.Dependency!.Get("readOnly")).Value);
                Assert.Empty(Assert.IsType<JsonArrayNode>(frozen.Dependency.Get("metadataFlags")).Items);
                MemberInfo flags = Assert.Single(members, member => member.MemberKey == Dependency(MetadataFixture.FlagsProperty));
                Assert.Equal(new[] { "AffectsMeasure", "AffectsArrange", "AffectsParentMeasure", "AffectsParentArrange", "AffectsRender", "Inherits", "OverridesInheritanceBehavior", "NotDataBindable", "BindsTwoWayByDefault", "Journal", "SubPropertiesDoNotAffectRender" }, Assert.IsType<JsonArrayNode>(flags.Dependency!.Get("metadataFlags")).Items.Select(Text).ToArray());
            });
        }

        [Fact]
        public void DependencyUnionUsesObjectIdentityAndDescriptorAttachedClassification()
        {
            Sta(() =>
            {
                var target = new ControlFixture();
                target.SetValue(ControlFixture.LocalProperty, 1);
                target.SetValue(AttachedOwner.LocalProperty, 2);
                DependencyPropertyDescriptor attachedDescriptor = DependencyPropertyDescriptor.FromProperty(AttachedOwner.LocalProperty, typeof(ControlFixture))!;
                Assert.True(attachedDescriptor.IsAttached);
                var provider = new Provider(typeof(ControlFixture), new PropertyDescriptor[] { attachedDescriptor, attachedDescriptor });
                TypeDescriptor.AddProvider(provider, target);
                try
                {
                    IReadOnlyList<MemberInfo> members = Catalog(target, out _);
                    MemberInfo attached = Assert.Single(members, member => member.MemberKey == Dependency(AttachedOwner.LocalProperty));
                    Assert.Equal("attachedProperty", attached.Category);
                    Assert.Equal("true", Text(attached.Dependency!.Get("isAttached")));
                    Assert.Null(attached.WrapperKey);
                    MemberInfo dependency = Assert.Single(members, member => member.MemberKey == Dependency(ControlFixture.LocalProperty));
                    Assert.Equal("dependencyProperty", dependency.Category);
                    Assert.Equal(Property(typeof(ControlFixture), "Local"), dependency.WrapperKey);
                    Assert.NotEqual(attached.MemberKey, dependency.MemberKey);
                }
                finally { TypeDescriptor.RemoveProvider(provider, target); }
            });
        }

        [Fact]
        public void TypeDescriptionDoesNotInitializeUnrelatedTypes()
        {
            staticCalls = 0;
            TypeInfoDto info = new ObjectInspector().DescribeType(typeof(Unrelated));
            Assert.Equal(typeof(Unrelated).FullName, info.FullName);
            Assert.Equal(0, staticCalls);
        }

        [Fact]
        public void CatalogDtosAreFreshAndCannotMutateCachedReflectionMetadata()
        {
            Sta(() =>
            {
                IReadOnlyList<MemberInfo> first = Catalog(new Model(), out _);
                MemberInfo modified = Assert.Single(first, member => member.MemberKey == Property(typeof(Model), "Virtual"));
                modified.Name = "mutated";
                modified.Readable = false;
                modified.Attributes = Array.Empty<AttributeInfo>();
                IReadOnlyList<MemberInfo> second = Catalog(new Model(), out _);
                ExactKeys(ModelKeys(), second);
                MemberInfo unchanged = Assert.Single(second, member => member.MemberKey == Property(typeof(Model), "Virtual"));
                Assert.Equal("Virtual", unchanged.Name);
                Assert.True(unchanged.Readable);
                Assert.Contains(unchanged.Attributes, attribute => attribute.TypeName == typeof(ProbeAttribute).FullName);
            });
        }

        [Fact]
        public void BrokenDescriptorDoesNotDiscardOtherDescriptors()
        {
            Sta(() =>
            {
                var target = new DynamicModel();
                var provider = new Provider(typeof(DynamicModel), new[] { new DynamicProperty("Broken", typeof(DynamicModel), typeof(int), true), new DynamicProperty("Good", typeof(DynamicModel), typeof(int)) });
                TypeDescriptor.AddProvider(provider, target);
                try
                {
                    IReadOnlyList<MemberInfo> members = Catalog(target, out List<Diagnostic> diagnostics);
                    ExactKeys(TypeKeys.Concat(new[] { Property(typeof(DynamicModel), "Existing"), Property(typeof(DynamicModel), "Invisible"), Descriptor(typeof(DynamicModel), "Good", typeof(int)) }), members);
                    Assert.Contains(diagnostics, diagnostic => diagnostic.Code == "discoveryFailed");
                }
                finally { TypeDescriptor.RemoveProvider(provider, target); }
            });
        }

        [Fact]
        public void CatalogOrderAndSerializedSnapshotsAreDeterministic()
        {
            Sta(() =>
            {
                foreach (object target in new object[] { new Model(), new DynamicModel(), new ControlFixture() })
                {
                    IReadOnlyList<MemberInfo> first = Catalog(target, out _);
                    IReadOnlyList<MemberInfo> second = Catalog(target, out _);
                    Assert.Equal(first.Select(member => Convert.ToBase64String(StrictJson.Serialize(member.ToJson()))), second.Select(member => Convert.ToBase64String(StrictJson.Serialize(member.ToJson()))));
                    Assert.Equal(first.OrderBy(member => member.Category, StringComparer.Ordinal).ThenBy(member => member.Name, StringComparer.Ordinal).ThenBy(member => member.DeclaringType, StringComparer.Ordinal).ThenBy(member => member.MemberKey, StringComparer.Ordinal).Select(member => member.MemberKey), first.Select(member => member.MemberKey));
                }
            });
        }

        [Fact]
        public void TypeMetadataHasCanonicalRowsAliasAndCompleteTypeDescription()
        {
            Sta(() =>
            {
                var inspector = new ObjectInspector();
                TypeInfoDto type = inspector.DescribeType(typeof(Model));
                Assert.Equal(nameof(Model), type.Name);
                Assert.Equal(typeof(Model).FullName, type.FullName);
                Assert.Equal(typeof(Model).Assembly.GetName().Name, type.AssemblyName);
                Assert.Equal(typeof(Model).AssemblyQualifiedName, type.AssemblyQualifiedName);
                Assert.Equal(new[] { typeof(ModelBase).FullName!, typeof(object).FullName! }, type.BaseTypes);
                TypeInfoDto.FromJson(type.ToJson());
                MemberInfo[] rows = Catalog(new Model(), out _).Where(member => member.Category == "typeMetadata").ToArray();
                ExactKeys(TypeKeys, rows);
                Assert.All(rows, row => { Assert.Equal(typeof(Model).FullName, row.DeclaringType); Assert.Equal("public", row.Visibility); Assert.True(row.Readable); Assert.Equal("type", row.PathSegment!.Kind); Assert.Equal("type:" + row.PathSegment.Name, row.MemberKey); });
                Assert.Equal("ClrFullClassName", Assert.Single(rows, row => row.MemberKey == "type:FullName").CompatibilityAlias);
                Assert.Single(rows, row => row.CompatibilityAlias != null);
                Assert.All(rows, row => Assert.Contains(row.Attributes, attribute => attribute.TypeName == typeof(ProbeAttribute).FullName));
            });
        }

        [Fact]
        public void MissingFullNameNeverFallsBackToToString()
        {
            var inspector = new ObjectInspector();
            TypeInfoDto type = inspector.DescribeType(new NamelessType());
            Assert.Equal("", type.FullName);
            Assert.Equal("", type.AssemblyQualifiedName);
            TypeInfoDto.FromJson(type.ToJson());
            Assert.Equal("", inspector.DescribeType(typeof(Dictionary<,>).GetGenericArguments()[0]).FullName);
        }
    }
}
