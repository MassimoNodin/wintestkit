import * as path from "node:path";
import Mocha from "mocha";

export function run(): Promise<void> {
  const mocha = new Mocha({ ui: "tdd", color: true, timeout: 60000 });
  const only = process.env.WTK_INTEGRATION_ONLY;
  for (const name of ["activation", "settings", "unused", "report"])
    if (!only || only === name) mocha.addFile(path.resolve(__dirname, name + ".test.js"));
  return new Promise((resolve, reject) => {
    mocha.run((failures) => {
      if (failures > 0)
        reject(new Error(failures + " integration tests failed"));
      else resolve();
    });
  });
}
