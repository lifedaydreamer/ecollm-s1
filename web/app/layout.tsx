import type { Metadata } from "next";
import "./style.css";
export const metadata: Metadata = {title: "TradePilot · 贸航 AI", description: "跨境交易多文档审查工作台"};
export default function Layout({children}: Readonly<{children: React.ReactNode}>) {return <html lang="zh-CN"><body>{children}</body></html>;}
