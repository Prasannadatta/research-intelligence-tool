import "@testing-library/jest-dom";

// Safe wrapper for JSDOM font-size resolution bug when computing styles on elements with calc() lengths
const origGetComputedStyle = window.getComputedStyle;
window.getComputedStyle = function (elt, pseudoElt) {
  try {
    return origGetComputedStyle.call(this, elt, pseudoElt);
  } catch {
    return origGetComputedStyle.call(this, window.document.createElement("div"), pseudoElt);
  }
};
