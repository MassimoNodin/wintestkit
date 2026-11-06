using System;
using System.ComponentModel;
using Snoop.Infrastructure;
using Xunit;

namespace WinTestKit.Inspector.Agent.Session.Tests;

[Trait("Category", "Unit")]
public class LauncherSnapshotTests
{
    [Fact]
    public void RetriesBadLengthAndDisposesFailedSnapshots()
    {
        int attempts = 0, disposed = 0;
        int result = NativeMethods.RetrySnapshot(() => ++attempts, value => value < 3, () => 24, _ => disposed++);
        Assert.Equal(3, result);
        Assert.Equal(2, disposed);
    }

    [Theory]
    [InlineData(5, 1)]
    [InlineData(24, 8)]
    public void SnapshotFailureIsNotTreatedAsAnEmptyModuleList(int code, int expectedAttempts)
    {
        int attempts = 0, disposed = 0;
        var error = Assert.Throws<Win32Exception>(() => NativeMethods.RetrySnapshot(
            () => ++attempts, _ => true, () => code, _ => disposed++));
        Assert.Equal(code, error.NativeErrorCode);
        Assert.Equal(expectedAttempts, attempts);
        Assert.Equal(expectedAttempts, disposed);
    }
}
