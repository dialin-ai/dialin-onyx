import { User, UserRole } from "@/lib/types";
import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { redirect } from "next/navigation";
import { ClientLayout } from "./ClientLayout";
import {
  NEXT_PUBLIC_CLOUD_ENABLED,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
} from "@/lib/constants";
import { AnnouncementBanner } from "../header/AnnouncementBanner";
import { fetchChatData } from "@/lib/chat/fetchChatData";
import { ChatProvider } from "../context/ChatContext";

export async function Layout({ children }: { children: React.ReactNode }) {
  const tasks = [getAuthTypeMetadataSS(), getCurrentUserSS()];

  // catch cases where the backend is completely unreachable here
  // without try / catch, will just raise an exception and the page
  // will not render
  let results: (User | AuthTypeMetadata | null)[] = [null, null];
  try {
    results = await Promise.all(tasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }

  const authTypeMetadata = results[0] as AuthTypeMetadata | null;
  const user = results[1] as User | null;
  const authDisabled = authTypeMetadata?.authType === "disabled";
  const requiresVerification = authTypeMetadata?.requiresVerification;

  if (!authDisabled) {
    if (!user) {
      return redirect("/auth/login");
    }
    if (user.role === UserRole.BASIC) {
      return redirect("/chat");
    }
    if (!user.is_verified && requiresVerification) {
      return redirect("/auth/waiting-on-verification");
    }
  }

  const data = await fetchChatData({});
  if ("redirect" in data) {
    redirect(data.redirect);
  }

  const {
    chatSessions,
    availableSources,
    documentSets,
    tags,
    llmProviders,
    folders,
    openedFolders,
    sidebarInitiallyVisible,
    defaultAssistantId,
    shouldShowWelcomeModal,
    ccPairs,
    inputPrompts,
    proSearchToggled,
  } = data;

  return (
    <ChatProvider
      value={{
        proSearchToggled,
        inputPrompts,
        chatSessions,
        sidebarInitiallyVisible,
        availableSources,
        ccPairs,
        documentSets,
        tags,
        availableDocumentSets: documentSets,
        availableTags: tags,
        llmProviders,
        folders,
        openedFolders,
        shouldShowWelcomeModal,
        defaultAssistantId,
      }}
    >
      <ClientLayout
        enableEnterprise={SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED}
        enableCloud={NEXT_PUBLIC_CLOUD_ENABLED}
        user={user}
      >
        <AnnouncementBanner />
        {children}
      </ClientLayout>
    </ChatProvider>
  );
}
