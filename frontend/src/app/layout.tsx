import type { Metadata } from "next";

import { NavBar } from "@/components/NavBar";
import { AuthProvider } from "@/lib/auth-context";
import { getServerSession } from "@/lib/auth-server";

import "./globals.css";

export const metadata: Metadata = {
  title: "Fleet",
  description: "Autonomous Fleet Management SaaS",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const session = await getServerSession();

  return (
    <html lang="en">
      <body>
        <AuthProvider initialSession={session}>
          <NavBar />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
