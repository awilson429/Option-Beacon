import {proxyOptionBeaconApi} from "@/lib/api-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(
  request: Request,
  context: {params: Promise<{path: string[]}>},
) {
  const {path} = await context.params;
  return proxyOptionBeaconApi(request, path);
}
