import * as path from "node:path";
import Mocha from "mocha";

export function run(): Promise<void> {
  const mocha = new Mocha({ ui: "tdd", color: true, timeout: 60000 });
  mocha.addFile(path.resolve(__dirname, "activation.test.js"));
  mocha.addFile(path.resolve(__dirname, "settings.test.js"));
  return new Promise((resolve, reject) => {
    mocha.run((failures) => {
      if (failures > 0)
        reject(new Error(failures + " integration tests failed"));
      else resolve();
    });
  });
}
