import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Botiva",
  description: "Business bots for Telegram and Bale, without a server.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return children;
}
