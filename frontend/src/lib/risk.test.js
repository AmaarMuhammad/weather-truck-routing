import { describe, expect, it } from "vitest";
import cases from "../../../shared/risk_cases.json";
import rules from "../../../shared/rules.json";
import { classify } from "./risk";

describe("classify (shared golden cases)", () => {
  for (const c of cases.cases) {
    it(c.note, () => {
      expect(classify(rules, c.wind, c.rain, c.snow, c.load)).toBe(c.level);
    });
  }

  it("missing data is Unknown, not Low", () => {
    expect(classify(rules, null, 0, 0, 0)).toBeNull();
  });
});
