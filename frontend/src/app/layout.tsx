import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";
import Providers from "@/components/Providers";
import AdblockWall from "@/components/AdblockWall";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Extractify - Download from Social Platforms",
  description:
    "Download anything from your favorite social platforms. Access high-quality downloads by simply pasting your URL.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable}`}>
      <body className="antialiased">
        <Providers>
          <AdblockWall>
            <Navbar />
            <main className="min-h-screen">{children}</main>
            <Footer />
          </AdblockWall>
        </Providers>
      </body>
    </html>
  );
}
