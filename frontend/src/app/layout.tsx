import "./globals.css";

export const metadata = {
  title: 'Sports BI Dashboard',
  description: 'Quantitative Analytics Terminal',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="antialiased overflow-x-hidden">
        {children}
      </body>
    </html>
  );
}
