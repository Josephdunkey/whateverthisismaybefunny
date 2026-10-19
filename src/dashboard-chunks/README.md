# Dashboard source chunks

这些文件是 Knowledge Hub 前端的分块源码，按 `01.js` → `10.js` 顺序拼接后写入：

```
D:\hermes agent\plugins\knowledge-hub\dashboard\dist\index.js
```

合并后必须通过：

```powershell
node --check "D:\hermes agent\plugins\knowledge-hub\dashboard\dist\index.js"
```

样式文件直接修改：

```
D:\hermes agent\plugins\knowledge-hub\dashboard\dist\style.css
```

注意：`01.js` 开头是 IIFE，`10.js` 结尾负责闭合与注册；不要单独修改某一块后忘记重新合并。