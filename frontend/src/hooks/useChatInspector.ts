/* 检查器/草稿入列状态（从 ChatView 抽出，工程债拆分 2026-08-31）。 */
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useUiStore } from "@/stores/uiStore";

export function useChatInspector() {
  const isWide = useMediaQuery("(min-width: 1280px)");
  const inspectorOpen = useUiStore((s) => s.inspectorOpen);
  const inspectorDrawerOpen = useUiStore((s) => s.inspectorDrawerOpen);
  const setInspectorDrawerOpen = useUiStore((s) => s.setInspectorDrawerOpen);
  const toggleInspector = useUiStore((s) => s.toggleInspector);
  const composerFocusTick = useUiStore((s) => s.composerFocusTick);
  return {
    isWide,
    inspectorOpen,
    inspectorDrawerOpen,
    setInspectorDrawerOpen,
    toggleInspector,
    composerFocusTick,
  };
}
