// SE4 플러그인 진입점. SE가 리플렉션으로 이 클래스를 찾아 DoAction을 부른다.
//
// **일은 파이썬이 한다.** 이 DLL은 SE와 검사기 사이의 다리일 뿐이다. 규정 검사·
// 교정·전사·번역이 전부 C#에 다시 구현되면 두 벌을 함께 고쳐야 하고, 그러면 반드시
// 어긋난다. 다리는 얇을수록 좋다.
// .NET Framework의 csc.exe는 C# 5까지만 안다. 표현식 본문 멤버(`=>`)를 쓰면
// 빌드가 안 된다 — 옛 문법으로 쓴다. 빌드에 SDK를 요구하지 않는 값이 그만큼 크다.
using System;
using System.Windows.Forms;

namespace Nikse.SubtitleEdit.PluginLogic
{
    public class SubtitleRuleChecker : IPlugin
    {
        string IPlugin.Name { get { return "자막 규정 검사기 (KO)"; } }

        string IPlugin.Text { get { return "자막 규정 검사·교정 / 영상에서 자막 만들기..."; } }

        decimal IPlugin.Version { get { return 0.1M; } }

        string IPlugin.Description
        {
            get
            {
                return "플랫폼 규정(SDH·번역)과 한국어 맞춤법으로 자막을 검사하고 고칩니다. " +
                       "영상만 있으면 전사·스포팅으로 초안을 만들고, 원어 스크립트가 있으면 " +
                       "대조해 한국어 초벌 번역까지 냅니다.";
            }
        }

        // "tool"이면 도구 메뉴에 붙는다. 이 플러그인은 자막을 통째로 바꾸므로
        // 번역(translate)이 아니라 도구가 맞다 — 번역만 하는 것이 아니다.
        string IPlugin.ActionType { get { return "tool"; } }

        string IPlugin.Shortcut { get { return string.Empty; } }

        string IPlugin.DoAction(Form parentForm, string subtitle, double frameRate,
                                string listViewLineSeparatorString, string subtitleFileName,
                                string videoFileName, string rawText)
        {
            // 자막이 없어도 막지 않는다. 영상만으로 초안을 만드는 것이 이 도구의
            // 핵심 기능이라, 빈 창에서 시작하는 것이 오히려 정상 경로다.
            using (var form = new PluginForm(subtitle, frameRate, subtitleFileName, videoFileName))
            {
                if (form.ShowDialog(parentForm) == DialogResult.OK)
                {
                    return form.ResultSubtitle ?? string.Empty;
                }
            }
            return string.Empty;   // 빈 문자열 = 자막을 그대로 둔다
        }
    }
}
