import type { Metadata } from 'next';
import '@fontsource-variable/manrope';
import './globals.css';
export const metadata: Metadata = { title: 'Ledger | Credit Appraisal Workbench', description: 'Evidence-led MSME credit appraisal, policy and portfolio operations.' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
