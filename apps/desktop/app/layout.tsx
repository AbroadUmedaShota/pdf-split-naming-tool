import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PDF整理ツール",
  description: "Local desktop shell for safe PDF organization."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
