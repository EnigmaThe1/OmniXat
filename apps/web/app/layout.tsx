import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OmniXat | Private Tax Control Centre",
  description: "Private-first UK tax and compliance dashboard",
  robots: { index: false, follow: false },
};

export default function RootLayout({children}:{children: React.ReactNode}) {
  return <html lang="en-GB"><body>{children}</body></html>;
}
