// Subtitle Edit 4 플러그인 계약. **우리가 정한 것이 아니다** —
// SubtitleEdit/plugins 저장소(source/*/DLL/IPlugin.cs)에 있는 것을 그대로 옮겼다.
// 한 글자라도 다르면 SE가 플러그인을 못 알아본다(리플렉션으로 찾는다).
using System.Windows.Forms;

namespace Nikse.SubtitleEdit.PluginLogic
{
    public interface IPlugin
    {
        string Name { get; }
        string Text { get; }
        decimal Version { get; }
        string Description { get; }

        /// <summary>file, tool, sync, translate, spellcheck 중 하나</summary>
        string ActionType { get; }

        string Shortcut { get; }

        string DoAction(Form parentForm, string subtitle, double frameRate,
                        string listViewLineSeparatorString, string subtitleFileName,
                        string videoFileName, string rawText);
    }
}
