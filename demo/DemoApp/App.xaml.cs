using System;
using System.Threading;
using System.Windows;

namespace DemoApp;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs args)
    {
        base.OnStartup(args);
        int slowStart = 0;
        int loadDelay = 2000;
        string title = "WTK Demo";

        for (int argumentIndex = 0; argumentIndex < args.Args.Length; argumentIndex++)
        {
            string argument = args.Args[argumentIndex];
            if (argumentIndex + 1 >= args.Args.Length)
            {
                continue;
            }
            string value = args.Args[argumentIndex + 1];
            if (argument == "--title")
            {
                title = value;
                argumentIndex++;
            }
            else if ((argument == "--slow-start" || argument == "--load-delay")
                     && int.TryParse(value, out int milliseconds) && milliseconds >= 0)
            {
                if (argument == "--slow-start")
                {
                    slowStart = milliseconds;
                }
                else
                {
                    loadDelay = milliseconds;
                }
                argumentIndex++;
            }
        }

        if (slowStart > 0)
        {
            Thread.Sleep(slowStart);
        }
        MainWindow = new MainWindow(loadDelay) { Title = title };
        MainWindow.Show();
    }
}
