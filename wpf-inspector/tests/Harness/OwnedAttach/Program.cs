using System.Text.RegularExpressions;

try
{
    if (args.Length == 4 && args[0] == "package")
    {
        PackageVerifier.Verify(args[1], args[2], args[3]);
        return 0;
    }
    if (args.Length == 5 && args[0] == "package-negative")
    {
        PackageNegativeTests.Run(args[1], args[2], args[3], args[4]);
        return 0;
    }
    if (args.Length >= 4 && args[0] == "attach")
    {
        await OwnedFixture.Run(args[1], args[2], args[3], args.Skip(4).ToArray());
        return 0;
    }
    Console.Error.WriteLine("Usage: OwnedAttach package <payload> <version> <upstream-commit> | attach <repo> <net48|net8|net10> <x86|x64> [--adverse] [--bad-token]");
    return 2;
}
catch (Exception error)
{
    // Bootstrap values, pipe messages, and token-bearing exceptions are never printed.
    Console.Error.WriteLine($"FAILED: {error.GetType().Name}: {Regex.Replace(error.Message, @"[A-Za-z0-9+/]{43}=", "[redacted]")}");
    return 1;
}
