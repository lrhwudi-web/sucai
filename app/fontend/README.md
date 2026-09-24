# Craftsman Golf Material Index Frontend

React + TypeScript 客户素材中心，包含英文品牌首页、真实账号登录、素材库和管理后台。管理后台支持待确认素材审核、按批次生成建议、选择或新建目录层级、批量入库、用户权限、日志以及 Drive/NAS 同步。

## 启动真实后端

在项目根目录启动 FastAPI：

```powershell
.\run-local.ps1
```

本地后端地址为 `http://127.0.0.1:8001`。

## 启动前端

```powershell
cd app\fontend
npm install
npm run dev
```

前端默认连接真实 FastAPI，不会在接口失败时静默切换成演示数据。Vite 会把 `/login`、`/logout`、`/auth`、`/api`、`/thumb`、`/media`、`/download`、`/sku` 和 `/admin` 代理到 `http://127.0.0.1:8001`。

- 客户首页：`http://127.0.0.1:4173/`
- 素材库：`http://127.0.0.1:4173/#catalogue`
- 管理后台：`http://127.0.0.1:4173/#admin`

素材库和管理后台都需要登录；非管理员账号不能进入管理后台。

钉钉登录由后端 `/auth/dingtalk/start` 发起。后端需要配置 `DINGTALK_CLIENT_ID` 和 `DINGTALK_CLIENT_SECRET`；生产环境建议额外设置 `DINGTALK_REDIRECT_URI=https://你的域名/auth/dingtalk/callback`，并在钉钉开放平台登记完全相同的回调地址。

## 构建与预览

```powershell
npm run build
npm run preview
```

开发与预览模式使用相同的后端代理配置。

## 显式使用演示数据

只有在纯视觉开发时才建议启用演示数据：

```powershell
$env:VITE_USE_API="false"
npm run dev
```

## 主要接口

- `GET /api/session`：读取当前登录账号和角色。
- `GET /auth/dingtalk/start`：发起钉钉 OAuth 登录。
- `GET /auth/dingtalk/callback`：校验 OAuth state、绑定本地账号并创建 Session。
- `GET /api/products`：读取账号可访问的产品分页。
- `GET /api/products/{sku}`：读取产品详情和真实素材文件。
- `POST /api/products/{sku}/zip`：创建产品素材 ZIP。
- `GET /api/admin/overview`：读取待确认素材、账号权限、日志、入库记录和同步状态。
- `/admin/*`：管理员审核、目录、账号、权限、同步和导入操作。

## 目录结构

- `src/components/`：客户首页、登录弹窗、导航、筛选、产品卡片和详情抽屉。
- `src/admin/`：待确认素材、批次操作、目录选择、权限、日志和同步界面。
- `src/services/`：认证、素材库和下载 API 客户端。
- `src/types.ts`：前端领域类型及 API 数据类型。
- `public/assets/`：品牌首页展示素材。
