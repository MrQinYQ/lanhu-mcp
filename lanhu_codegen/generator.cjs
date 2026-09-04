/* Official HTML generator, module 24c8. See source-manifest.json. */
const { readLoopPath } = require("./safe-path.cjs");

module.exports = function (schema, option) {
  var _ = option._,
    prettier = option.prettier,
    template = [],
    imports = [],
    utils = [],
    datas = [],
    constants = {},
    methods = [],
    expressionName = [],
    lifeCycles = [],
    flexStyle = [
      ".flex-col {\n        display: flex;\n        flex-direction: column;\n    }",
      ".flex-row {\n        display: flex;\n        flex-direction: row;\n    }",
      ".justify-start {\n        display: flex;\n        justify-content: flex-start;\n    }",
      ".justify-center {\n        display: flex;\n        justify-content: center;\n    }",
      "\n    .justify-end {\n        display: flex;\n        justify-content: flex-end;\n    }",
      ".justify-evenly {\n        display: flex;\n        justify-content: space-evenly;\n    }",
      ".justify-around {\n        display: flex;\n        justify-content: space-around;\n    }",
      ".justify-between {\n        display: flex;\n        justify-content: space-between;\n    }",
      ".align-start {\n        display: flex;\n        align-items: flex-start;\n    }",
      ".align-center {\n        display: flex;\n        align-items: center;\n    }",
      ".align-end {\n        display: flex;\n        align-items: flex-end;\n    }",
    ],
    commonStyle = [
      "body * {\n      box-sizing: border-box;\n      flex-shrink: 0;\n    }",
      "body {\n      font-family: PingFangSC-Regular,Roboto,Helvetica Neue,Helvetica,Tahoma,Arial,PingFang SC-Light,Microsoft YaHei;\n    }",
      "input {\n      background-color: transparent;\n      border: 0;\n    }",
      "button {\n      margin: 0;\n      padding: 0;\n      border: 1px solid transparent;\n      outline: none;\n      background-color: transparent;\n    }",
      "\n    button:active {\n     opacity: .6;\n    }",
    ].concat(flexStyle),
    justifyContentKey = {
      "flex-start": "justify-start",
      center: "justify-center",
      "flex-end": "justify-end",
      "space-between": "justify-between",
      "space-around": "justify-around",
    },
    alignItemKey = {
      "flex-start": "align-start",
      center: "align-center",
      "flex-end": "align-end",
    },
    styles = [],
    styles4vw = [],
    styles4rem = [],
    boxStyleList = [
      "fontSize",
      "marginTop",
      "marginBottom",
      "paddingTop",
      "paddingBottom",
      "height",
      "top",
      "bottom",
      "width",
      "maxWidth",
      "left",
      "right",
      "paddingRight",
      "paddingLeft",
      "marginLeft",
      "marginRight",
      "lineHeight",
      "borderBottomRightRadius",
      "borderBottomLeftRadius",
      "borderTopRightRadius",
      "borderTopLeftRadius",
    ],
    complexStyleList = ["background", "backgroundSize", "margin", "padding"],
    noUnitStyles = ["opacity", "fontWeight"],
    lifeCycleMap = {
      _constructor: "created",
      getDerivedStateFromProps: "beforeUpdate",
      render: "",
      componentDidMount: "mounted",
      componentDidUpdate: "updated",
      componentWillUnmount: "beforeDestroy",
    },
    width = option.responsive.width || 375,
    viewportWidth = option.responsive.viewportWidth || 375,
    htmlFontsize = option.responsive.remVal || 37.5,
    _w = width / 100,
    _ratio = width / viewportWidth,
    reverseLoopchildren = function reverseLoopchildren(
      loopData,
      loopChildren,
      firstIndex,
      loopNum
    ) {
      if (
        ((loopChildren.props.className = ""
          .concat(loopChildren.props.className, "-")
          .concat(firstIndex)),
        loopChildren.nthConfig)
      ) {
        var rowNum = loopChildren.nthConfig[0].match(/[1-9]+/g)[0],
          colNum = loopChildren.nthConfig[1].match(/[1-9]+/g)[0];
        Number(firstIndex + 1) % rowNum === 0 &&
          (loopChildren.props.style["marginRight"] = 0),
          Number(loopNum - firstIndex) <= colNum &&
            (loopChildren.props.style["marginBottom"] = 0);
      }
      switch (loopChildren.type) {
        case "lanhubutton":
        case "lanhublock":
          if (
            loopChildren.styleObj &&
            Object.keys(loopChildren.styleObj).length
          ) {
            var blockLoopStyle = Object.keys(loopChildren.styleObj);
            blockLoopStyle.map(function (item) {
              var loopStylekey = loopChildren.styleObj[item].replace(
                "item.",
                ""
              );
              (loopChildren.props.style["background"] = readLoopPath(loopData, loopStylekey)),
                loopChildren.props.style["background"] ||
                  delete loopChildren.props.style["background"],
                delete loopChildren.styleObj,
                delete loopChildren.props.styleObj;
            });
          }
          break;
        case "lanhuimage":
        case "lanhutext":
          if (loopChildren.data.value.indexOf("item.") > -1) {
            var loopStylekey = loopChildren.data.value.replace(
              "this.item.",
              ""
            );
            (loopChildren.data.value = readLoopPath(loopData, loopStylekey)),
              "lanhuimage" === loopChildren.type
                ? (loopChildren.props.src = readLoopPath(loopData, loopStylekey))
                : (loopChildren.props.text = readLoopPath(loopData, loopStylekey));
          }
          if (
            loopChildren.styleObj &&
            Object.keys(loopChildren.styleObj).length
          ) {
            var _blockLoopStyle = Object.keys(loopChildren.styleObj);
            _blockLoopStyle.map(function (item) {
              var loopStylekey = loopChildren.styleObj[item].replace(
                "item.",
                ""
              );
              (loopChildren.props.style["color"] = readLoopPath(loopData, loopStylekey)),
                delete loopChildren.styleObj,
                delete loopChildren.props.styleObj;
            });
          }
          break;
      }
      if (loopChildren.children.length) {
        var i = loopChildren.children.length;
        while (i--) {
          var curChild = loopChildren.children[i],
            specialSlot = curChild.specialSlot,
            slot = curChild.slot;
          if (specialSlot) {
            if (void 0 === loopData["slot" + slot]) {
              loopChildren.children.splice(i, 1);
              continue;
            }
            delete curChild.condition,
              delete curChild.specialSlot,
              delete curChild.specialData,
              delete curChild.slot;
          }
          reverseLoopchildren(
            loopData,
            loopChildren.children[i],
            firstIndex,
            loopNum
          );
        }
      }
    },
    reverseLoop = function e(t) {
      if (t.loopData && t.loopData.length > 0) {
        var n = t.loopData.length;
        t.children = t.loopData.reduce(function (e, r, i) {
          var s = _.cloneDeep(t.children[0]);
          return reverseLoopchildren(r, s, i, n), e.push(s), e;
        }, []);
      }
      t.children.length &&
        t.children.forEach(function (t) {
          e(t);
        });
    };
  reverseLoop(schema);
  var isExpression = function (e) {
      return /^\{\{.*\}\}$/.test(e);
    },
    transformEventName = function (e) {
      return e.replace("on", "").toLowerCase();
    },
    toString = function (e) {
      return "[object Function]" === {}.toString.call(e)
        ? e.toString()
        : "string" === typeof e
        ? e
        : "object" === typeof e
        ? JSON.stringify(e, function (e, t) {
            return "function" === typeof t ? t.toString() : t;
          })
        : String(e);
    },
    parseStyle = function (e) {
      var t =
          arguments.length > 1 && void 0 !== arguments[1] ? arguments[1] : {},
        n = t.toVW,
        r = t.toREM,
        i = [];
      for (var s in e) {
        var o = e[s];
        if (
          ("borderWidth" === s && (o += "px"), -1 != boxStyleList.indexOf(s))
        ) {
          if (n)
            (o =
              "font-size" === _.kebabCase(s)
                ? Math.floor((100 * parseInt(o)) / _w) / 100
                : Math.ceil((100 * parseInt(o)) / _w) / 100),
              (o = 0 == o ? o : o + "vw");
          else if (r && htmlFontsize) {
            var a = "string" == typeof o ? o.replace(/(px)|(rem)/, "") : o;
            (o =
              "font-size" === _.kebabCase(s)
                ? Math.floor((1e3 * parseInt(a)) / htmlFontsize) / 1e3
                : Math.ceil((1e3 * parseInt(a)) / htmlFontsize) / 1e3),
              (o = o ? "".concat(o, "rem") : o);
          } else (o = parseInt(o).toFixed(2)), (o = 0 == o ? o : o + "px");
          i.push("".concat(_.kebabCase(s), ": ").concat(o));
        } else
          -1 != complexStyleList.indexOf(s)
            ? (n
                ? ["margin", "padding", "background-size"].includes(
                    _.kebabCase(s)
                  )
                  ? (o = o.replace(
                      /([0-9]+\.[0-9]+|[0-9]+)(rem|px)/g,
                      function (e, t, n) {
                        var r = Math.floor((100 * parseInt(t)) / _w) / 100;
                        return r + "vw";
                      }
                    ))
                  : ["background"].includes(_.kebabCase(s)) &&
                    (o = o.replace(/\)\s(.*)\sno\-repeat/, function (e, t, n) {
                      return e.replace(
                        t,
                        "".concat(
                          t.replace(
                            /([0-9]+\.[0-9]+|[0-9]+)(rem|px)/g,
                            function (e, t, n) {
                              var r = Math.ceil((100 * parseInt(t)) / _w) / 100;
                              return r + "vw";
                            }
                          )
                        )
                      );
                    }))
                : r &&
                  htmlFontsize &&
                  (["margin", "padding", "background-size"].includes(
                    _.kebabCase(s)
                  )
                    ? (o = o.replace(
                        /([0-9]+\.[0-9]+|[0-9]+)(rem|px)/g,
                        function (e, t, n) {
                          var r =
                            Math.ceil((1e3 * parseInt(t)) / htmlFontsize) / 1e3;
                          return r + "rem";
                        }
                      ))
                    : ["background"].includes(_.kebabCase(s)) &&
                      (o = o.replace(
                        /\)\s(.*)\sno\-repeat/,
                        function (e, t, n) {
                          return e.replace(
                            t,
                            "".concat(
                              t.replace(
                                /([0-9]+\.[0-9]+|[0-9]+)(rem|px)/g,
                                function (e, t, n) {
                                  var r =
                                    Math.ceil(
                                      (1e3 * parseInt(t)) / htmlFontsize
                                    ) / 1e3;
                                  return r + "rem";
                                }
                              )
                            )
                          );
                        }
                      ))),
              i.push("".concat(_.kebabCase(s), ": ").concat(o)))
            : -1 != noUnitStyles.indexOf(s)
            ? i.push(
                ""
                  .concat(_.kebabCase(s), ": ")
                  .concat(isNaN(parseFloat(o)) ? o : parseFloat(o))
              )
            : s.indexOf("Webkit") > -1
            ? i.push("-".concat(_.kebabCase(s), ": ").concat(o))
            : i.push("".concat(_.kebabCase(s), ": ").concat(o));
      }
      return i.join(";");
    },
    parseFunction = function (e) {
      var t = e.toString(),
        n = t
          .slice(t.indexOf("function"), t.indexOf("("))
          .replace("function ", ""),
        r = t.match(/\([^\(\)]*\)/)[0].slice(1, -1),
        i = t.slice(t.indexOf("{") + 1, t.lastIndexOf("}"));
      return { params: r, content: i, name: n };
    },
    parseProps = function (e, t, n) {
      if ("string" === typeof e) {
        if (isExpression(e))
          return t ? "{{".concat(e.slice(7, -2), "}}") : e.slice(2, -2);
        if (t) return e;
        if (n) {
          expressionName[n] = expressionName[n] ? expressionName[n] + 1 : 1;
          var r = "".concat(n).concat(expressionName[n]);
          return (constants[r] = e), '"constants.'.concat(r, '"');
        }
        return '"'.concat(e, '"');
      }
      if ("function" === typeof e) {
        var i = parseFunction(e),
          s = i.params,
          o = i.content,
          a = i.name;
        return (
          (expressionName[a] = expressionName[a] ? expressionName[a] + 1 : 1),
          methods.push(
            ""
              .concat(a, "_")
              .concat(expressionName[a], "(")
              .concat(s, ") {")
              .concat(o, "}")
          ),
          "".concat(a, "_").concat(expressionName[a])
        );
      }
      return '"'.concat(e, '"');
    },
    parsePropsKey = function (e, t) {
      return "function" === typeof t
        ? "@".concat(transformEventName(e))
        : ":".concat(e);
    },
    parseDataSource = function (e) {
      var t = e.id,
        n = e.options,
        r = n.uri,
        i = n.method,
        s = n.params,
        o = e.type,
        a = {};
      switch (o) {
        case "fetch":
          -1 === imports.indexOf("import {fetch} from whatwg-fetch") &&
            imports.push("import {fetch} from 'whatwg-fetch'"),
            (a = { method: i });
          break;
        case "jsonp":
          -1 === imports.indexOf("import {fetchJsonp} from fetch-jsonp") &&
            imports.push("import jsonp from 'fetch-jsonp'");
          break;
      }
      Object.keys(e.options).forEach(function (t) {
        -1 === ["uri", "method", "params"].indexOf(t) &&
          (a[t] = toString(e.options[t]));
      }),
        (a = s
          ? ""
              .concat(toString(a).slice(0, -1), " ,body: ")
              .concat(isExpression(s) ? parseProps(s) : toString(s), "}")
          : toString(a));
      var u = "{\n      "
        .concat(o, "(")
        .concat(parseProps(r), ", ")
        .concat(
          toString(a),
          ")\n        .then((response) => response.json())\n    "
        );
      if (e.dataHandler) {
        var c = parseFunction(e.dataHandler),
          l = c.params,
          p = c.content;
        u += ".then(("
          .concat(l, ") => {")
          .concat(
            p,
            "})\n        .catch((e) => {\n          console.log('error', e);\n        })\n      "
          );
      }
      return (u += "}"), "".concat(t, "() ").concat(u);
    },
    parseCondition = function (e, t) {
      var n = isExpression(e) ? e.slice(2, -2) : e;
      return (
        "string" === typeof n && (n = n.replace("this.", "")),
        (t = t.replace(
          /^<\w+\s/,
          "".concat(t.match(/^<\w+\s/)[0], ' v-if="').concat(n, '" ')
        )),
        t
      );
    },
    parseLoop = function (e, t, n) {
      var r,
        i = (t && t[0]) || "item",
        s = (t && t[1]) || "index";
      Array.isArray(e)
        ? ((r = "loopData"), datas.push("".concat(r, ": ").concat(toString(e))))
        : isExpression(e) && (r = e.slice(2, -2).replace("this.state.", ""));
      var o = n.indexOf(">"),
        a = -1 == n.slice(0, o).indexOf("key=") ? ':key="'.concat(s, '"') : "";
      n = "\n      "
        .concat(n.slice(0, o), '\n      v-for="(')
        .concat(i, ", ")
        .concat(s, ") in ")
        .concat(r, '"  \n      ')
        .concat(a, "\n      ")
        .concat(n.slice(o));
      var u = new RegExp("this.".concat(i), "g");
      return (n = n.replace(u, i)), n;
    },
    generateRender = function (e) {
      var t,
        n = e.componentName.toLowerCase(),
        r = e.props && e.props.className,
        i = getCommonStyle(e),
        s = r ? ' class="'.concat(r).concat(i ? " " + i : "", '"') : "";
      r &&
        (styles.push(
          "\n        ."
            .concat(r, " {\n          ")
            .concat(parseStyle(e.props.style), "\n        }\n      ")
        ),
        styles4vw.push(
          "\n        ."
            .concat(r, " {\n          ")
            .concat(
              parseStyle(e.props.style, { toVW: !0 }),
              "\n        }\n      "
            )
        ),
        styles4rem.push(
          "\n        ."
            .concat(r, " {\n          ")
            .concat(
              parseStyle(e.props.style, { toREM: !0 }),
              "\n        }\n      "
            )
        ));
      var o = "";
      switch (
        (Object.keys(e.props).forEach(function (t) {
          -1 ===
            ["className", "style", "text", "src", "lines", "onClick"].indexOf(
              t
            ) &&
            (o += " "
              .concat(parsePropsKey(t, e.props[t]), "=")
              .concat(parseProps(e.props[t])));
        }),
        n)
      ) {
        case "lanhutext":
          var a = parseProps(e.props.text, !0);
          t = "<span".concat(s).concat(o, ">").concat(a, "</span> ");
          break;
        case "lanhuimage":
          var u = parseProps(e.props.src, !1);
          u.match('"')
            ? (t = "<img"
                .concat(s)
                .concat(o, ' referrerpolicy="no-referrer" src=')
                .concat(u, " /> "))
            : ((u = '"'.concat(u, '"')),
              (t = "<img"
                .concat(s)
                .concat(o, ' referrerpolicy="no-referrer" :src=')
                .concat(u, " /> ")));
          break;
        case "lanhudiv":
        case "lanhublock":
        case "lanhupage":
          t =
            e.children && e.children.length
              ? "<div"
                  .concat(s)
                  .concat(o, ">")
                  .concat(transform(e.children), "</div>")
              : "<div".concat(s).concat(o, " ></div>");
          break;
        case "lanhubutton":
          t =
            e.children && e.children.length
              ? "<button"
                  .concat(s)
                  .concat(o, ">")
                  .concat(transform(e.children), "</button>")
              : "<button".concat(s).concat(o, " ></button>");
          break;
        default:
          t =
            e.children && e.children.length
              ? "<div"
                  .concat(s)
                  .concat(o, ">")
                  .concat(transform(e.children), "</div>")
              : "<div".concat(s).concat(o, " ></div>");
      }
      if (e.uiType)
        switch (e.uiType) {
          case "InputArea":
            var c =
              (e.uiTypeProb && e.uiTypeProb.placeholder) ||
              (e.props && e.props.text ? parseProps(e.props.text, !0) : "");
            c.search(/item\.(?:specialSlot[0-9]+\.)?lanhutext[0-9]+/) < 0 &&
              (t = "<input"
                .concat(s)
                .concat(o, ' placeholder="')
                .concat(c, '" style="width:')
                .concat(e.style.width, "px;height:")
                .concat(e.style.height, 'px;" />'));
            break;
        }
      return e.condition && (t = parseCondition(e.condition, t)), t || "";
    },
    getCommonStyle = function (e) {
      var t = e.props.style.flexDirection,
        n = "",
        r = e.alignJustify,
        i = void 0 === r ? {} : r,
        s = i.justifyContent,
        o = void 0 === s ? "" : s,
        a = i.alignItems,
        u = void 0 === a ? "" : a;
      return (
        t &&
          ((n = "row" === t ? "flex-row" : "flex-col"),
          delete e.props.style.display,
          delete e.props.style.flexDirection),
        justifyContentKey[o] &&
          ((n = n
            ? "".concat(n, " ").concat(justifyContentKey[o])
            : justifyContentKey[o]),
          delete e.props.style.display,
          delete e.props.style.flexDirection,
          delete e.props.style["justifyContent"]),
        alignItemKey[u] &&
          ((n = n
            ? "".concat(n, " ").concat(alignItemKey[u])
            : alignItemKey[u]),
          delete e.props.style.display,
          delete e.props.style.flexDirection,
          delete e.props.style["alignItems"]),
        n
      );
    },
    transform = function e(t) {
      var n = "";
      if (Array.isArray(t))
        t.forEach(function (t) {
          n += e(t);
        });
      else {
        var r = t.componentName.toLowerCase();
        if (-1 !== ["lanhupage", "block", "component"].indexOf(r)) {
          var i = [];
          if (
            (t.state && datas.push("".concat(toString(t.state).slice(1, -1))),
            t.methods &&
              Object.keys(t.methods).forEach(function (e) {
                var n = parseFunction(t.methods[e]),
                  r = n.params,
                  i = n.content;
                methods.push("".concat(e, "(").concat(r, ") {").concat(i, "}"));
              }),
            t.dataSource &&
              Array.isArray(t.dataSource.list) &&
              (t.dataSource.list.forEach(function (e) {
                "boolean" === typeof e.isInit && e.isInit
                  ? i.push("this.".concat(e.id, "();"))
                  : "string" === typeof e.isInit &&
                    i.push(
                      "if ("
                        .concat(parseProps(e.isInit), ") { this.")
                        .concat(e.id, "(); }")
                    ),
                  methods.push(parseDataSource(e));
              }),
              t.dataSource.dataHandler))
          ) {
            var s = parseFunction(t.dataSource.dataHandler),
              o = s.params,
              a = s.content;
            methods.push("dataHandler(".concat(o, ") {").concat(a, "}")),
              i.push("this.dataHandler()");
          }
          t.lifeCycles &&
            (t.lifeCycles["_constructor"] ||
              lifeCycles.push(
                ""
                  .concat(lifeCycleMap["_constructor"], "() { ")
                  .concat(i.join("\n"), "}")
              ),
            Object.keys(t.lifeCycles).forEach(function (e) {
              var n = lifeCycleMap[e] || e,
                r = parseFunction(t.lifeCycles[e]),
                s = (r.params, r.content);
              "_constructor" === e
                ? lifeCycles.push(
                    ""
                      .concat(n, "() {")
                      .concat(s, " ")
                      .concat(i.join("\n"), "}")
                  )
                : lifeCycles.push("".concat(n, "() {").concat(s, "}"));
            })),
            template.push(generateRender(t));
        } else n += generateRender(t);
      }
      return n;
    };
  option.utils &&
    Object.keys(option.utils).forEach(function (e) {
      utils.push("const ".concat(e, " = ").concat(option.utils[e]));
    }),
    styles4rem.push(
      "\n    html {\n      font-size:".concat(htmlFontsize, "px\n    }\n  ")
    ),
    transform(schema),
    datas.push("constants: ".concat(toString(constants)));
  var prettierOpt = {
    parser: "vue",
    printWidth: 80,
    singleQuote: !0,
    htmlWhitespaceSensitivity: "ignore",
  };
  return {
    panelDisplay: [
      {
        panelName: "index.html",
        panelValue:
          '\n          <!DOCTYPE html>\n          <html lang="en">\n          <head>\n              <meta charset="UTF-8">\n              <meta name="viewport" content="width=device-width, initial-scale=1.0">\n              <title>Document</title>\n              <link rel="stylesheet" type="text/css" href="./common.css" />\n              <link rel="stylesheet" type="text/css" href="./index.css" />\n          </head>\n          <body>\n            '.concat(
            template,
            "\n          </body>\n          </html>\n        "
          ),
        panelType: "html5",
      },
      {
        panelName: "index.css",
        panelValue: "".concat(styles.join("\n")),
        panelType: "css",
      },
      {
        panelName: "index.rem.css",
        panelValue: styles4rem.join("\n"),
        panelType: "css",
      },
      {
        panelName: "index.response.css",
        panelValue: styles4vw.join("\n"),
        panelType: "css",
      },
      {
        panelName: "common.css",
        panelValue: "".concat(commonStyle.join("\n")),
        panelType: "css",
      },
    ],
    renderData: {
      template: template,
      imports: imports,
      datas: datas,
      methods: methods,
      lifeCycles: lifeCycles,
      styles: styles,
    },
    noTemplate: !0,
  };
};
