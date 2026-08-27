/* 首次运行欢迎遮罩（R15）：一屏三步引导卡，克制精致。
 *
 * 显示条件：localStorage ra.onboarded.v1 缺失（useFirstRunWizard）。
 * 「开始使用」/ Esc / 点击背景均可关闭并写标记；步骤 CTA 直接跳对应页
 * 并同样完成引导。framer-motion 入场，useEscapeStack 保证与其它浮层的
 * Esc 层级语义一致。
 */
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { LogoMark } from "@/components/icons";
import { useEscapeStack } from "@/hooks/useEscapeStack";
import { useFirstRunWizard } from "@/hooks/useFirstRunWizard";

const STEP_CARD =
  "flex items-start gap-3.5 rounded-2xl border border-edge bg-canvas px-4 py-3.5 text-left";

export function FirstRunWizard() {
  const { show, dismiss } = useFirstRunWizard();
  const navigate = useNavigate();
  useEscapeStack(show, dismiss);

  if (!show) return null;

  const go = (to: string) => {
    dismiss();
    navigate(to);
  };

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      onMouseDown={dismiss}
    >
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-label="欢迎使用研究助手"
        className="w-full max-w-xl rounded-3xl border border-edge bg-surface p-7 shadow-card"
        initial={{ opacity: 0, y: 18, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.24, ease: "easeOut" }}
        onMouseDown={(event) => event.stopPropagation()}
      >
        {/* 品牌区 */}
        <div className="flex items-center gap-3">
          <LogoMark className="h-11 w-11 rounded-[12px] shadow-sm" />
          <div>
            <div className="text-[17px] font-semibold leading-tight">研究助手</div>
            <div className="text-[11px] leading-tight text-ink-3">Research Assistant</div>
          </div>
        </div>

        <h1 className="mt-5 text-lg font-semibold tracking-tight">欢迎使用研究助手</h1>
        <p className="mt-1 text-[13px] text-ink-2">
          三步开始你的第一项深度研究——文献、证据与成稿全程可追溯。
        </p>

        <div className="mt-4 space-y-2.5">
          <div className={STEP_CARD}>
            <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-tint text-[11px] font-semibold text-accent-hover dark:text-accent">
              1
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium">配置模型 API</div>
              <p className="mt-0.5 text-[12px] leading-5 text-ink-3">
                填入服务商与 API Key，写入后即刻生效，驱动整条研究流水线。
              </p>
            </div>
            <button
              type="button"
              onClick={() => go("/settings")}
              className="shrink-0 self-center rounded-xl bg-accent px-3.5 py-2 text-[12.5px] font-semibold text-white transition-colors hover:bg-accent-hover"
            >
              前往设置
            </button>
          </div>

          <div className={STEP_CARD}>
            <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-tint text-[11px] font-semibold text-accent-hover dark:text-accent">
              2
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium">发起第一项研究</div>
              <p className="mt-0.5 text-[12px] leading-5 text-ink-3">
                在会话中描述课题，Agent 会按「规划 → 研究 → 写作 → 定稿」推进。
              </p>
            </div>
            <button
              type="button"
              onClick={() => go("/chat")}
              className="shrink-0 self-center rounded-xl border border-edge px-3.5 py-2 text-[12.5px] font-medium transition-colors hover:border-accent/50 hover:text-accent"
            >
              打开会话
            </button>
          </div>

          <div className={STEP_CARD}>
            <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-tint text-[11px] font-semibold text-accent-hover dark:text-accent">
              3
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium">全局搜索随手可达</div>
              <p className="mt-0.5 text-[12px] leading-5 text-ink-3">
                任意页面按{" "}
                <kbd className="rounded border border-edge px-1.5 py-0.5 font-mono text-[10px]">
                  Ctrl K
                </kbd>{" "}
                即可直达线程、任务、资料与产物。
              </p>
            </div>
          </div>
        </div>

        <div className="mt-5 flex items-center justify-between gap-3">
          <span className="text-[11px] text-ink-3">仅首次显示 · Esc 也可关闭</span>
          <button
            type="button"
            onClick={dismiss}
            autoFocus
            className="rounded-xl bg-accent px-5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover"
          >
            开始使用
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
