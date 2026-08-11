// 검사기를 찾아 실행한다.
//
// 경로 찾기가 이 파일의 전부다. SE 플러그인은 `%appdata%\Subtitle Edit\Plugins`에
// 놓이므로 저장소가 어디 있는지 스스로 알 수 없다. 한 번 찾으면 ini에 적어 두고
// 다음부터는 묻지 않는다.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;

namespace Nikse.SubtitleEdit.PluginLogic
{
    internal static class Runner
    {
        public static string SettingsPath
        {
            get
            {
                var dir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "Subtitle Edit", "Plugins");
                Directory.CreateDirectory(dir);
                return Path.Combine(dir, "subtitle-rule-checker.ini");
            }
        }

        public static Dictionary<string, string> LoadSettings()
        {
            var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (!File.Exists(SettingsPath))
            {
                return map;
            }
            foreach (var line in File.ReadAllLines(SettingsPath, Encoding.UTF8))
            {
                var at = line.IndexOf('=');
                if (at > 0 && !line.TrimStart().StartsWith("#"))
                {
                    map[line.Substring(0, at).Trim()] = line.Substring(at + 1).Trim();
                }
            }
            return map;
        }

        public static void SaveSettings(Dictionary<string, string> map)
        {
            var sb = new StringBuilder();
            sb.AppendLine("# 자막 규정 검사기 설정. 지우면 다시 묻습니다.");
            foreach (var pair in map)
            {
                sb.AppendLine(pair.Key + "=" + pair.Value);
            }
            File.WriteAllText(SettingsPath, sb.ToString(), new UTF8Encoding(false));
        }

        /// <summary>저장소 폴더. 못 찾으면 null — 부르는 쪽이 사용자에게 묻는다.</summary>
        public static string FindRepo()
        {
            var fromEnv = Environment.GetEnvironmentVariable("CHECKER_REPO");
            if (IsRepo(fromEnv))
            {
                return fromEnv;
            }

            string saved;
            if (LoadSettings().TryGetValue("repo", out saved) && IsRepo(saved))
            {
                return saved;
            }

            // 흔히 두는 자리. 사용자가 옮겼으면 못 찾고, 그러면 물어본다.
            var docs = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            foreach (var guess in new[]
                     {
                         Path.Combine(docs, "subtitle-editor"),
                         Path.Combine(docs, "GitHub", "subtitle-editor"),
                     })
            {
                if (IsRepo(guess))
                {
                    return guess;
                }
            }
            return null;
        }

        public static bool IsRepo(string path)
        {
            return !string.IsNullOrEmpty(path)
                   && Directory.Exists(Path.Combine(path, "checker"))
                   && File.Exists(Path.Combine(path, "checker", "cli.py"));
        }

        /// <summary>
        /// 파이썬을 찾는다. 한국어 교정기의 가상환경을 먼저 본다 — 검사기의
        /// 한국어 레인이 거기 붙어 있어, 그 파이썬으로 돌려야 교정까지 된다.
        /// </summary>
        public static string FindPython(string repo)
        {
            var fromEnv = Environment.GetEnvironmentVariable("CHECKER_PYTHON");
            if (!string.IsNullOrEmpty(fromEnv) && File.Exists(fromEnv))
            {
                return fromEnv;
            }

            var parent = Directory.GetParent(repo);
            if (parent != null)
            {
                var venv = Path.Combine(parent.FullName, "korean-subtitle-corrector",
                                        ".venv", "Scripts", "python.exe");
                if (File.Exists(venv))
                {
                    return venv;
                }
            }
            return "python";   // PATH에 맡긴다
        }

        public static string CorrectorPath(string repo)
        {
            var parent = Directory.GetParent(repo);
            if (parent == null)
            {
                return null;
            }
            var ksc = Path.Combine(parent.FullName, "korean-subtitle-corrector");
            return Directory.Exists(ksc) ? ksc : null;
        }

        /// <summary>
        /// 검사기를 돌리고 나오는 줄을 그때그때 넘긴다. 전사와 번역은 몇 분씩
        /// 걸리므로 끝날 때까지 아무것도 안 보이면 멈춘 줄 안다.
        /// </summary>
        public static int Run(string repo, string arguments, Action<string> onLine)
        {
            var python = FindPython(repo);
            var info = new ProcessStartInfo(python, "-m checker " + arguments)
            {
                WorkingDirectory = repo,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };
            // 파이썬이 콘솔 코드페이지를 따라가면 한글이 깨진다. 창이 없으므로
            // 더더욱 UTF-8로 못을 박는다.
            info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            info.EnvironmentVariables["PYTHONUTF8"] = "1";
            var ksc = CorrectorPath(repo);
            if (ksc != null && string.IsNullOrEmpty(
                    Environment.GetEnvironmentVariable("KSC_PATH")))
            {
                info.EnvironmentVariables["KSC_PATH"] = ksc;
            }

            using (var process = new Process { StartInfo = info })
            {
                process.OutputDataReceived += (s, e) => { if (e.Data != null) onLine(e.Data); };
                process.ErrorDataReceived += (s, e) => { if (e.Data != null) onLine(e.Data); };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                process.WaitForExit();
                return process.ExitCode;
            }
        }

        public static string Quote(string path)
        {
            return "\"" + path + "\"";
        }

        /// <summary>작업용 임시 폴더. 원본 자막이 있는 곳을 건드리지 않는다.</summary>
        public static string TempDir()
        {
            var dir = Path.Combine(Path.GetTempPath(),
                                   "subtitle-rule-checker-" + Guid.NewGuid().ToString("N").Substring(0, 8));
            Directory.CreateDirectory(dir);
            return dir;
        }
    }
}
