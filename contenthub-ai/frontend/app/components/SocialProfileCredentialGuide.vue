<script setup lang="ts">
import { BookOpen, ExternalLink } from 'lucide-vue-next'

const props = defineProps<{ platformKey: string, platformName: string }>()

interface CredentialGuide {
  portal: string
  docs: string
  steps: string[]
  scopes: string[]
}

const metaPortal = 'https://developers.facebook.com/apps/'
const guides: Record<string, CredentialGuide | undefined> = {
  facebook: {
    portal: metaPortal,
    docs: 'https://developers.facebook.com/documentation/development/create-an-app',
    steps: [
      'Create a Meta app with the Manage everything on your Page use case. Copy the App ID and App Secret from App Settings → Basic.',
      'Enable the Page permissions below and register the callback under Facebook Login settings.',
      'In ContentHub, authorize with a Facebook account that manages the Page and select the Page as the target.',
    ],
    scopes: ['pages_show_list', 'pages_manage_posts', 'pages_read_engagement'],
  },
  instagram: {
    portal: metaPortal,
    docs: 'https://developers.facebook.com/documentation/instagram-platform/content-publishing',
    steps: [
      'Link your Instagram Business or Creator account to a Facebook Page you manage.',
      'Set up Instagram API with Facebook Login in your Meta app. Use the App ID and App Secret from App Settings → Basic and register the callback in Facebook Login settings.',
      'Authorize with Facebook and select the Instagram account. You can also enter a Facebook Page access token and the Instagram professional account ID under Credentials.',
      'For API publishing, attach a JPEG that ContentHub can serve over public HTTPS.',
    ],
    scopes: ['instagram_basic', 'instagram_content_publish', 'pages_read_engagement', 'pages_show_list'],
  },
  threads: {
    portal: metaPortal,
    docs: 'https://developers.facebook.com/documentation/threads/get-started',
    steps: [
      'Create a Meta app with the Access the Threads API use case. Open its Threads settings for the Threads App ID and App Secret.',
      'Register the callback in the Threads use case settings. Add your Threads account as a tester while developing, then authorize that account in ContentHub.',
    ],
    scopes: ['threads_basic', 'threads_content_publish'],
  },
  linkedin: {
    portal: 'https://www.linkedin.com/developers/apps',
    docs: 'https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow',
    steps: [
      'Create an app. Under Products, add Sign In with LinkedIn using OpenID Connect and Share on LinkedIn for member posting.',
      'Copy the Client ID and Client Secret from the Auth tab. Add the callback under Authorized redirect URLs.',
      'For a company Page, request Community Management API access. Obtain a user token with openid, profile, w_organization_social and rw_organization_admin, enter it under Credentials, then select the organization as the target.',
    ],
    scopes: ['openid', 'profile', 'w_member_social'],
  },
  google_business_profile: {
    portal: 'https://console.cloud.google.com/',
    docs: 'https://developers.google.com/my-business/content/prereqs',
    steps: [
      'Create a Google Cloud project, request Business Profile API access, and enable the Business Profile APIs for the approved project.',
      'Set up the OAuth consent screen and create a Web application OAuth client. Add the callback and copy the Client ID and Client Secret.',
      'Authorize using a Google account that manages the verified Business Profile and select the location in ContentHub.',
    ],
    scopes: ['https://www.googleapis.com/auth/business.manage'],
  },
  pinterest: {
    portal: 'https://developers.pinterest.com/apps/',
    docs: 'https://developers.pinterest.com/docs/getting-started/connect-app/',
    steps: [
      'Sign in with a Pinterest business account. Under My apps, choose Connect app and request Trial access.',
      'After approval, open the app in My apps for the App ID and App Secret. Add the callback in the Configure tab.',
      'Use Standard access for public Pins. Authorize the account, select a board, and attach an image to the test draft.',
    ],
    scopes: ['boards:read', 'pins:read', 'pins:write'],
  },
  twitter: {
    portal: 'https://console.x.com/',
    docs: 'https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code',
    steps: [
      'Create an app in the X Developer Console and enable OAuth 2.0 user authentication with read and write access.',
      'Register the callback, then copy the OAuth 2.0 Client ID and the Client Secret if your app uses one.',
      'X API publishing uses paid credits and requires explicit authorization in ContentHub. Manual publishing is available.',
    ],
    scopes: ['tweet.read', 'tweet.write', 'users.read', 'offline.access'],
  },
}

const guide = computed(() => guides[props.platformKey])
const open = ref(false)
const callback = ref('')

function openGuide() {
  callback.value = `${window.location.origin}/connected-accounts?oauth_callback=1`
  open.value = true
}
</script>

<template>
  <UButton color="neutral" variant="ghost" size="xs" @click="openGuide">
    <BookOpen class="h-3.5 w-3.5" />
    Credential Setup
  </UButton>

  <UModal v-model:open="open" :title="`${platformName} credential setup`">
    <template #body>
      <div v-if="guide" class="space-y-4 text-sm">
        <div class="flex flex-wrap gap-2">
          <UButton :href="guide.portal" target="_blank" rel="noopener noreferrer" color="neutral" variant="outline" size="xs">
            Developer Portal <ExternalLink class="h-3 w-3" />
          </UButton>
          <UButton :href="guide.docs" target="_blank" rel="noopener noreferrer" color="neutral" variant="outline" size="xs">
            Official Instructions <ExternalLink class="h-3 w-3" />
          </UButton>
        </div>
        <ol class="list-decimal space-y-2 pl-5">
          <li v-for="step in guide.steps" :key="step">{{ step }}</li>
        </ol>
        <div>
          <p class="font-medium">OAuth callback URI</p>
          <code class="break-all text-xs">{{ callback }}</code>
          <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Register the exact URI. If the platform requires HTTPS, use the callback from your HTTPS ContentHub deployment.
          </p>
        </div>
        <div>
          <p class="font-medium">OAuth permissions</p>
          <div class="mt-1 flex flex-wrap gap-1">
            <UBadge v-for="scope in guide.scopes" :key="scope" color="neutral" variant="subtle" size="xs">
              {{ scope }}
            </UBadge>
          </div>
        </div>
        <p>Enter the app credentials under Connected Accounts → Connect OAuth for this profile.</p>
      </div>
      <p v-else class="text-sm">
        This profile uses manual publishing and needs no API credentials. Create your draft in ContentHub and publish it on the platform directly.
      </p>
    </template>
  </UModal>
</template>
