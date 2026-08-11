// 플러그인 창. 코드로 짜고 디자이너 파일을 두지 않는다 — .resx가 없으면
// csc.exe 하나로 빌드되고, 빌드가 쉬우면 남이 고쳐 쓸 수 있다.
//
// **바꾼 자막을 곧바로 SE에 밀어넣지 않는다.** 먼저 리포트를 보여 주고, 사람이
// [SE에 반영]을 눌렀을 때만 돌려준다. 자동 교정이 틀렸을 때 되돌릴 자리를 남기는
// 것이 이 도구가 사람을 대하는 방식이다.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace Nikse.SubtitleEdit.PluginLogic
{
    public class PluginForm : Form
    {
        private readonly string _subtitle;
        private readonly double _frameRate;
        private readonly string _subtitleFileName;
        private readonly string _videoFileName;
        private readonly Dictionary<string, string> _settings;

        private ComboBox _platform, _kind, _marker, _collision, _moveTo;
        private CheckBox _korean, _fixTiming, _translate;
        private TextBox _script, _video, _log;
        private Button _check, _fix, _generate, _apply, _close;
        private Label _status;
        private string _repo;

        public string ResultSubtitle { get; private set; }

        public PluginForm(string subtitle, double frameRate, string subtitleFileName,
                          string videoFileName)
        {
            _subtitle = subtitle ?? string.Empty;
            _frameRate = frameRate > 0 ? frameRate : 23.976;
            _subtitleFileName = subtitleFileName ?? string.Empty;
            _videoFileName = videoFileName ?? string.Empty;
            _settings = Runner.LoadSettings();
            _repo = Runner.FindRepo();
            Build();
        }

        private void Build()
        {
            Text = "자막 규정 검사기";
            StartPosition = FormStartPosition.CenterParent;
            ClientSize = new Size(760, 620);
            MinimumSize = new Size(660, 520);
            Font = new Font("Malgun Gothic", 9F);

            var top = new TableLayoutPanel
            {
                Dock = DockStyle.Top, ColumnCount = 4, Height = 210, Padding = new Padding(8),
                AutoSize = false,
            };
            top.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 70));
            top.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
            top.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 70));
            top.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

            _platform = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
            _platform.Items.AddRange(new object[] { "netflix", "disney", "coupang" });
            _platform.SelectedItem = Get("platform", "netflix");

            _kind = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
            _kind.Items.AddRange(new object[] { "sdh", "translation" });
            _kind.SelectedItem = Get("kind", "sdh");

            top.Controls.Add(new Label { Text = "플랫폼", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 0, 0);
            top.Controls.Add(_platform, 1, 0);
            top.Controls.Add(new Label { Text = "종류", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 2, 0);
            top.Controls.Add(_kind, 3, 0);

            _video = new TextBox { Dock = DockStyle.Fill, Text = _videoFileName };
            var videoPick = new Button { Text = "찾기", Width = 60, Dock = DockStyle.Right };
            videoPick.Click += (s, e) => Pick(_video, "영상 파일|*.mp4;*.mkv;*.mov;*.avi;*.ts|모든 파일|*.*");
            var videoRow = new Panel { Dock = DockStyle.Fill, Height = 26 };
            videoRow.Controls.Add(_video);
            videoRow.Controls.Add(videoPick);
            top.Controls.Add(new Label { Text = "영상", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 0, 1);
            top.SetColumnSpan(videoRow, 3);
            top.Controls.Add(videoRow, 1, 1);

            _script = new TextBox { Dock = DockStyle.Fill, Text = Get("script", "") };
            var scriptPick = new Button { Text = "찾기", Width = 60, Dock = DockStyle.Right };
            scriptPick.Click += (s, e) => Pick(_script, "스크립트|*.txt;*.md;*.srt|모든 파일|*.*");
            var scriptRow = new Panel { Dock = DockStyle.Fill, Height = 26 };
            scriptRow.Controls.Add(_script);
            scriptRow.Controls.Add(scriptPick);
            top.Controls.Add(new Label { Text = "원어 대본", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 0, 2);
            top.SetColumnSpan(scriptRow, 3);
            top.Controls.Add(scriptRow, 1, 2);

            // **작업마다 달라지는 것.** 화면자막을 무엇으로 표시하는지, 말자막과
            // 겹칠 때 어떻게 하는지는 업체와 작업에 따라 다르다(작업자 자료
            // [영상번역] 673·677·678행). 정하지 않으면 검사기가 위치를 건드리지
            // 않는다 — 추측해서 옮기면 납품물이 틀어진다.
            _marker = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
            _marker.Items.AddRange(new object[] { "(작업 시작 전 선택)", "double_quote", "italic", "bracket", "none" });
            _marker.SelectedItem = Get("marker", "(작업 시작 전 선택)");

            _collision = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
            _collision.Items.AddRange(new object[] { "(작업 시작 전 선택)", "move_dialogue", "dialogue_only", "keep_both" });
            _collision.SelectedItem = Get("collision", "(작업 시작 전 선택)");

            _moveTo = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
            _moveTo.Items.AddRange(new object[] { "top_center", "top_left", "top_right",
                                                  "bottom_center", "bottom_left", "bottom_right" });
            _moveTo.SelectedItem = Get("moveTo", "top_center");

            top.Controls.Add(new Label { Text = "화면자막", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 0, 4);
            top.Controls.Add(_marker, 1, 4);
            top.Controls.Add(new Label { Text = "겹치면", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 2, 4);
            top.Controls.Add(_collision, 3, 4);
            top.Controls.Add(new Label { Text = "옮길 자리", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 0, 5);
            top.Controls.Add(_moveTo, 1, 5);

            _korean = new CheckBox { Text = "한국어 교정기", Checked = Get("korean", "1") == "1", AutoSize = true };
            _fixTiming = new CheckBox { Text = "타임코드 수렴", Checked = Get("fixTiming", "0") == "1", AutoSize = true };
            _translate = new CheckBox { Text = "한국어 초벌 번역(만들기)", Checked = Get("translate", "0") == "1", AutoSize = true };
            var checks = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true };
            checks.Controls.AddRange(new Control[] { _korean, _fixTiming, _translate });
            top.SetColumnSpan(checks, 3);
            top.Controls.Add(new Label { Text = "옵션", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 0, 3);
            top.Controls.Add(checks, 1, 3);

            _log = new TextBox
            {
                Dock = DockStyle.Fill, Multiline = true, ReadOnly = true,
                ScrollBars = ScrollBars.Vertical, Font = new Font("Consolas", 9F),
                BackColor = Color.White,
            };

            _status = new Label { Dock = DockStyle.Bottom, Height = 20, Text = "" };

            var buttons = new FlowLayoutPanel
            {
                Dock = DockStyle.Bottom, Height = 42, FlowDirection = FlowDirection.RightToLeft,
                Padding = new Padding(6),
            };
            _close = new Button { Text = "닫기", Width = 80, DialogResult = DialogResult.Cancel };
            _apply = new Button { Text = "SE에 반영", Width = 110, Enabled = false };
            _generate = new Button { Text = "영상에서 자막 만들기", Width = 160 };
            _fix = new Button { Text = "검사 + 교정", Width = 110 };
            _check = new Button { Text = "검사만", Width = 90 };
            buttons.Controls.AddRange(new Control[] { _close, _apply, _generate, _fix, _check });

            _check.Click += (s, e) => Start(false);
            _fix.Click += (s, e) => Start(true);
            _generate.Click += (s, e) => StartGenerate();
            _apply.Click += (s, e) => { DialogResult = DialogResult.OK; Close(); };
            CancelButton = _close;

            Controls.Add(_log);
            Controls.Add(top);
            Controls.Add(_status);
            Controls.Add(buttons);

            if (_repo == null)
            {
                Say("검사기 저장소를 찾지 못했습니다. [폴더 지정]을 눌러 subtitle-editor 폴더를 알려 주세요.");
                var pick = new Button { Text = "폴더 지정", Width = 90 };
                pick.Click += (s, e) => PickRepo();
                buttons.Controls.Add(pick);
                _check.Enabled = _fix.Enabled = _generate.Enabled = false;
            }
            else
            {
                Say("검사기: " + _repo);
                if (string.IsNullOrEmpty(_subtitle))
                {
                    Say("자막이 열려 있지 않습니다. 영상만 있으면 [영상에서 자막 만들기]로 시작하세요.");
                    _check.Enabled = _fix.Enabled = false;
                }
            }
        }

        private string Get(string key, string fallback)
        {
            string value;
            return _settings.TryGetValue(key, out value) && value.Length > 0 ? value : fallback;
        }

        private void Pick(TextBox target, string filter)
        {
            using (var dialog = new OpenFileDialog { Filter = filter })
            {
                if (target.Text.Length > 0)
                {
                    try { dialog.InitialDirectory = Path.GetDirectoryName(target.Text); }
                    catch { /* 경로가 이상해도 창은 떠야 한다 */ }
                }
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    target.Text = dialog.FileName;
                }
            }
        }

        private void PickRepo()
        {
            using (var dialog = new FolderBrowserDialog { Description = "subtitle-editor 폴더를 고르세요" })
            {
                if (dialog.ShowDialog(this) != DialogResult.OK)
                {
                    return;
                }
                if (!Runner.IsRepo(dialog.SelectedPath))
                {
                    MessageBox.Show(this, "그 폴더에는 checker\\cli.py가 없습니다.", "폴더가 다릅니다",
                                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                _repo = dialog.SelectedPath;
                _settings["repo"] = _repo;
                Runner.SaveSettings(_settings);
                Say("검사기: " + _repo);
                _check.Enabled = _fix.Enabled = _subtitle.Length > 0;
                _generate.Enabled = true;
            }
        }

        private void Say(string line)
        {
            if (InvokeRequired)
            {
                BeginInvoke((Action<string>)Say, line);
                return;
            }
            _log.AppendText(line + Environment.NewLine);
        }

        private void Busy(bool busy, string what)
        {
            if (InvokeRequired)
            {
                BeginInvoke((Action<bool, string>)Busy, busy, what);
                return;
            }
            _check.Enabled = _fix.Enabled = _generate.Enabled = !busy;
            _status.Text = busy ? what : string.Empty;
            Cursor = busy ? Cursors.WaitCursor : Cursors.Default;
        }

        private void Remember()
        {
            _settings["platform"] = (string)_platform.SelectedItem;
            _settings["kind"] = (string)_kind.SelectedItem;
            _settings["korean"] = _korean.Checked ? "1" : "0";
            _settings["fixTiming"] = _fixTiming.Checked ? "1" : "0";
            _settings["translate"] = _translate.Checked ? "1" : "0";
            _settings["script"] = _script.Text;
            _settings["marker"] = (string)_marker.SelectedItem;
            _settings["collision"] = (string)_collision.SelectedItem;
            _settings["moveTo"] = (string)_moveTo.SelectedItem;
            if (_repo != null)
            {
                _settings["repo"] = _repo;
            }
            Runner.SaveSettings(_settings);
        }


        private string JobArgs()
        {
            // "(작업 시작 전 선택)"은 아직 정하지 않았다는 뜻이다. 그대로 넘기지
            // 않는다 — 검사기가 정해야 한다고 말해 준다.
            var args = new StringBuilder();
            var marker = (string)_marker.SelectedItem;
            var collision = (string)_collision.SelectedItem;
            if (marker != null && !marker.StartsWith("("))
            {
                args.Append(" --fn-marker ").Append(marker);
            }
            if (collision != null && !collision.StartsWith("("))
            {
                args.Append(" --collision ").Append(collision);
                if (collision == "move_dialogue")
                {
                    args.Append(" --collision-move-to ").Append(_moveTo.SelectedItem);
                }
            }
            return args.ToString();
        }

        private void Start(bool applyFixes)
        {
            Remember();
            var work = Runner.TempDir();
            var input = Path.Combine(work, "input.srt");
            var output = Path.Combine(work, "fixed.srt");
            // SE는 자막을 SubRip 텍스트로 넘겨준다. 파일로 떨어뜨려 검사기에 준다.
            File.WriteAllText(input, _subtitle, new UTF8Encoding(false));

            var args = new StringBuilder();
            args.Append(Runner.Quote(input));
            args.Append(" -p ").Append(_platform.SelectedItem);
            args.Append(" -k ").Append(_kind.SelectedItem);
            args.Append(" --fps ").Append(_frameRate.ToString(
                System.Globalization.CultureInfo.InvariantCulture));
            if (_korean.Checked)
            {
                args.Append(" --korean");
            }
            if (_fixTiming.Checked)
            {
                args.Append(" --fix-timing");
            }
            args.Append(JobArgs());
            if (applyFixes)
            {
                args.Append(" --fix -o ").Append(Runner.Quote(output));
            }

            RunAsync(args.ToString(), applyFixes ? output : null,
                     applyFixes ? "검사하고 고치는 중입니다..." : "검사 중입니다...");
        }

        private void StartGenerate()
        {
            if (_video.Text.Length == 0 || !File.Exists(_video.Text))
            {
                MessageBox.Show(this, "영상 파일을 골라 주세요.", "영상이 없습니다",
                                MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            Remember();

            var work = Runner.TempDir();
            var output = Path.Combine(work, "draft.srt");
            var args = new StringBuilder();
            args.Append("--generate --video ").Append(Runner.Quote(_video.Text));
            args.Append(" -p ").Append(_platform.SelectedItem);
            args.Append(" -k ").Append(_kind.SelectedItem);
            args.Append(" -o ").Append(Runner.Quote(output));
            if (_script.Text.Length > 0)
            {
                args.Append(" --script ").Append(Runner.Quote(_script.Text));
            }
            args.Append(JobArgs());
            if (_translate.Checked)
            {
                args.Append(" --translate");
            }

            Say("");
            Say("영상 길이에 비례해 걸립니다. 전사는 실시간의 20배쯤, 번역은 그보다 느립니다.");
            RunAsync(args.ToString(), output, "자막을 만드는 중입니다...");
        }

        private void RunAsync(string arguments, string expectedOutput, string what)
        {
            Busy(true, what);
            var repo = _repo;
            var thread = new Thread(() =>
            {
                int code = -1;
                try
                {
                    code = Runner.Run(repo, arguments, Say);
                }
                catch (Exception ex)
                {
                    Say("[오류] " + ex.Message);
                }

                if (expectedOutput != null && File.Exists(expectedOutput))
                {
                    var text = File.ReadAllText(expectedOutput, Encoding.UTF8);
                    BeginInvoke((Action)(() =>
                    {
                        ResultSubtitle = text;
                        _apply.Enabled = true;
                        _apply.Focus();
                        Say("");
                        Say("결과가 준비됐습니다. [SE에 반영]을 누르면 SE의 자막이 바뀝니다"
                            + "(SE에서 Ctrl+Z로 되돌릴 수 있습니다).");
                        // 만든 자막 옆에 노트 파일이 있으면 알려 준다. 봐야 할 자리다.
                        var notes = Path.ChangeExtension(expectedOutput, ".notes.srt");
                        if (File.Exists(notes))
                        {
                            Say("봐야 할 자리: " + notes);
                            Say("  SE에서 [파일 - 원본 자막 열기]로 얹으면 나란히 보입니다.");
                        }
                    }));
                }
                else if (expectedOutput != null && code == 0)
                {
                    Say("고칠 것이 없어 결과 파일이 나오지 않았습니다.");
                }

                Busy(false, null);
            });
            thread.IsBackground = true;
            thread.Start();
        }
    }
}
