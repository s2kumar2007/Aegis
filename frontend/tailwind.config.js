export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0a0c0f",
        panel: "#11151a",
        line: "#1f2732",
        amber: "#e0a336",
        danger: "#e5484d",
        ok: "#3ecf8e",
        muted: "#7a8794",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
