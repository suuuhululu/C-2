import React from "react";
import { createRoot } from "react-dom/client";
import Monitor from "./monitor/Monitor";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Monitor />
  </React.StrictMode>,
);
