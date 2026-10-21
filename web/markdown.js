    function appendInlineMarkdown(parent, text) {
      const tokenPattern = /(\*\*[^*\n]+?\*\*|`[^`\n]+`|\*[^*\n]+?\*)/g;
      let position = 0;

      for (const match of text.matchAll(tokenPattern)) {
        const token = match[0];
        parent.appendChild(document.createTextNode(text.slice(position, match.index)));

        let element;
        let value;
        if (token.startsWith("**")) {
          element = document.createElement("strong");
          value = token.slice(2, -2);
        } else if (token.startsWith("`")) {
          element = document.createElement("code");
          value = token.slice(1, -1);
        } else {
          element = document.createElement("em");
          value = token.slice(1, -1);
        }
        element.textContent = value;
        parent.appendChild(element);
        position = match.index + token.length;
      }

      parent.appendChild(document.createTextNode(text.slice(position)));
    }

    function createMarkdownList(type) {
      return document.createElement(type === "ordered" ? "ol" : "ul");
    }

    function renderMarkdown(text, container) {
      const lines = text.replace(/\r\n?/g, "\n").split("\n");
      let index = 0;

      while (index < lines.length) {
        if (!lines[index].trim()) {
          index += 1;
          continue;
        }

        if (/^\s*```/.test(lines[index])) {
          const pre = document.createElement("pre");
          const code = document.createElement("code");
          const block = [];
          index += 1;
          while (index < lines.length && !/^\s*```/.test(lines[index])) {
            block.push(lines[index++]);
          }
          if (index < lines.length) index += 1;
          code.textContent = block.join("\n");
          pre.appendChild(code); container.appendChild(pre);
          continue;
        }

        const heading = lines[index].match(/^(#{1,3})\s+(.+)$/);
        if (heading) {
          const element = document.createElement(`h${heading[1].length}`);
          appendInlineMarkdown(element, heading[2]);
          container.appendChild(element);
          index += 1;
          continue;
        }

        const firstItem = lines[index].match(/^([ \t]*)([-*+]|\d+[.)])\s+(.+)$/);
        if (firstItem) {
          const indentWidth = (value) => value.replace(/\t/g, "  ").length;
          const firstIndent = indentWidth(firstItem[1]);
          const firstType = /^\d/.test(firstItem[2]) ? "ordered" : "unordered";
          const rootList = createMarkdownList(firstType);
          container.appendChild(rootList);
          const stack = [{
            indent: firstIndent,
            type: firstType,
            list: rootList,
            item: null
          }];

          while (index < lines.length) {
            const item = lines[index].match(/^([ \t]*)([-*+]|\d+[.)])\s+(.+)$/);
            if (!item) break;

            const indent = indentWidth(item[1]);
            const type = /^\d/.test(item[2]) ? "ordered" : "unordered";
            while (stack.length > 1 && indent < stack[stack.length - 1].indent) {
              stack.pop();
            }

            let current = stack[stack.length - 1];
            if (indent === current.indent && type !== current.type) break;

            if (indent > current.indent) {
              if (!current.item) break;
              const nestedList = createMarkdownList(type);
              current.item.appendChild(nestedList);
              current = {
                indent,
                type,
                list: nestedList,
                item: null
              };
              stack.push(current);
            }

            const listItem = document.createElement("li");
            appendInlineMarkdown(listItem, item[3]);
            current.list.appendChild(listItem);
            current.item = listItem;
            index += 1;
          }
          continue;
        }

        const paragraphLines = [];
        while (index < lines.length && lines[index].trim()) {
          if (
            paragraphLines.length > 0 &&
            (/^(#{1,3})\s+/.test(lines[index]) ||
              /^([ \t]*)([-*+]|\d+[.)])\s+/.test(lines[index]))
          ) {
            break;
          }
          paragraphLines.push(lines[index].trim());
          index += 1;
        }

        if (paragraphLines.length) {
          const paragraph = document.createElement("p");
          appendInlineMarkdown(paragraph, paragraphLines.join(" "));
          container.appendChild(paragraph);
        }
      }
    }
