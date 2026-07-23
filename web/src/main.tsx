import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { SettingsProvider } from "./lib/settings";
import Layout from "./components/Layout";
import Home from "./pages/Home";
import Market from "./pages/Market";
import Ticker from "./pages/Ticker";
import News from "./pages/News";
import Learn from "./pages/Learn";
import Brief from "./pages/Brief";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SettingsProvider>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/market/:market" element={<Market />} />
            <Route path="/ticker/:market/:code" element={<Ticker />} />
            <Route path="/news" element={<News />} />
            <Route path="/brief" element={<Brief />} />
            <Route path="/learn" element={<Learn />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </SettingsProvider>
  </StrictMode>,
);
