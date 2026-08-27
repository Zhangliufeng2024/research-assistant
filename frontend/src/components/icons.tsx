import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const strokeDefaults = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
} as const;

/** 品牌 logo：赤陶渐变圆角方块 + 米白星芒（与桌面图标 packaging/app_icon.ico 同源）。 */
export function LogoMark(props: IconProps) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden {...props}>
      <defs>
        <linearGradient id="ra-logo-g" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#E28E68" />
          <stop offset="1" stopColor="#C0582F" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14.5" fill="url(#ra-logo-g)" />
      <path
        d="M32 12 Q34.5 29.5 52 32 Q34.5 34.5 32 52 Q29.5 34.5 12 32 Q29.5 29.5 32 12 Z"
        fill="#FBF7EE"
      />
    </svg>
  );
}

export function IconChat(props: IconProps) {
  return (
    <svg {...strokeDefaults} {...props}>
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5Z" />
    </svg>
  );
}

export function IconTasks(props: IconProps) {
  return (
    <svg {...strokeDefaults} {...props}>
      <path d="m3 17 2 2 4-4" />
      <path d="m3 7 2 2 4-4" />
      <path d="M13 6h8" />
      <path d="M13 12h8" />
      <path d="M13 18h8" />
    </svg>
  );
}

export function IconLibrary(props: IconProps) {
  return (
    <svg {...strokeDefaults} {...props}>
      <path d="M2 4h6a4 4 0 0 1 4 4v12a3 3 0 0 0-3-3H2z" />
      <path d="M22 4h-6a4 4 0 0 0-4 4v12a3 3 0 0 1 3-3h7z" />
    </svg>
  );
}

export function IconSettings(props: IconProps) {
  return (
    <svg {...strokeDefaults} {...props}>
      <line x1="21" x2="14" y1="4" y2="4" />
      <line x1="10" x2="3" y1="4" y2="4" />
      <line x1="21" x2="12" y1="12" y2="12" />
      <line x1="8" x2="3" y1="12" y2="12" />
      <line x1="21" x2="16" y1="20" y2="20" />
      <line x1="12" x2="3" y1="20" y2="20" />
      <line x1="14" x2="14" y1="2" y2="6" />
      <line x1="8" x2="8" y1="10" y2="14" />
      <line x1="16" x2="16" y1="18" y2="22" />
    </svg>
  );
}

export function IconSun(props: IconProps) {
  return (
    <svg {...strokeDefaults} {...props}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2" />
      <path d="M12 20v2" />
      <path d="m4.93 4.93 1.41 1.41" />
      <path d="m17.66 17.66 1.41 1.41" />
      <path d="M2 12h2" />
      <path d="M20 12h2" />
      <path d="m6.34 17.66-1.41 1.41" />
      <path d="m19.07 4.93-1.41 1.41" />
    </svg>
  );
}

export function IconMoon(props: IconProps) {
  return (
    <svg {...strokeDefaults} {...props}>
      <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    </svg>
  );
}

/** 总览：项目主页（R15 导航收敛新增，lucide home 同风格）。 */
export function IconHome(props: IconProps) {
  return (
    <svg {...strokeDefaults} {...props}>
      <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <path d="M9 22V12h6v10" />
    </svg>
  );
}

/** 研究工作台：锥形瓶（R15 导航收敛新增，lucide flask-conical 同风格）。 */
export function IconFlask(props: IconProps) {
  return (
    <svg {...strokeDefaults} {...props}>
      <path d="M10 2v7.5a2 2 0 0 1-.2.9L4.7 20.5a1 1 0 0 0 .9 1.5h12.8a1 1 0 0 0 .9-1.5L14.2 10.4a2 2 0 0 1-.2-.9V2" />
      <path d="M8.5 2h7" />
      <path d="M7 16h10" />
    </svg>
  );
}

/** 通知入口：铃铛（R15 侧栏撤出通知中心后的顶栏入口）。 */
export function IconBell(props: IconProps) {
  return (
    <svg {...strokeDefaults} {...props}>
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}
