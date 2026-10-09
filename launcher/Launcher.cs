// RushSuite.exe - tiny native launcher. Starts the bundled portable Python runtime
// (runtime\pythonw.exe) with app\main.py, so no Python installation is needed.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("RushSuite")]
[assembly: System.Reflection.AssemblyProduct("RushSuite")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

static class Launcher
{
    [STAThread]
    static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string py = Path.Combine(root, "runtime", "pythonw.exe");
        string main = Path.Combine(root, "app", "main.py");
        if (!File.Exists(py) || !File.Exists(main))
        {
            MessageBox.Show("RushSuite files are missing.\n\nKeep RushSuite.exe inside its folder together " +
                            "with the 'runtime', 'app' and 'models' folders.", "RushSuite",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        string argLine = "\"" + main + "\"";
        foreach (string a in args) argLine += " \"" + a.Replace("\"", "") + "\"";

        var psi = new ProcessStartInfo(py, argLine);
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false;
        // isolate from any other Python installed on this PC
        psi.EnvironmentVariables.Remove("PYTHONPATH");
        psi.EnvironmentVariables.Remove("PYTHONHOME");
        psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        try
        {
            Process.Start(psi);
        }
        catch (Exception e)
        {
            MessageBox.Show("Could not start RushSuite:\n" + e.Message, "RushSuite",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        return 0;
    }
}
