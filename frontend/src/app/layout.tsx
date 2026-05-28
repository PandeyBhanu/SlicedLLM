import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import MainLayout from "@/components/layout/main-layout"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "SlicedLLM - PromptOps Platform",
  description: "AI Prompt Versioning and Evaluation Platform",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <MainLayout>{children}</MainLayout>
      </body>
    </html>
  )
}
