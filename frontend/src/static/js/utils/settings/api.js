const urlParse = require('url-parse');

let BASE_URL = null;
let ENDPOINTS = null;

function endpointsIter(ret, endpoints) {
  const baseUrl = BASE_URL.toString().replace(/\/+$/, '');

  for (let k in endpoints) {
    if ('string' === typeof endpoints[k]) {
      ret[k] = baseUrl + '/' + endpoints[k].replace(/^\//g, '');
    } else {
      endpointsIter(ret[k], endpoints[k]);
    }
  }
}

function formatEndpoints(endpoints) {
  const baseUrl = BASE_URL.toString();
  const ret = endpoints;
  endpointsIter(ret, endpoints);
  return ret;
}

export function init(base_url, endpoints) {

  console.log("endpoints",endpoints);
  BASE_URL = urlParse(base_url);

  ENDPOINTS = formatEndpoints({
    media: endpoints.media,
    wowzaLive: endpoints.wowza_live,
    featured: endpoints.media + '?show=featured',
    recommended: endpoints.media + '?show=recommended',
    playlists: endpoints.playlists,
    users: endpoints.members,
    user: {
      liked: endpoints.liked,
      history: endpoints.history,
      purchases: endpoints.purchases,
      playlists: endpoints.playlists + '?author=',
      live: endpoints.live + '?author=',
    },
    archive: {
      tags: endpoints.tags,
      categories: endpoints.categories,
      ads : endpoints.ads,
      category_ads : endpoints.category_ads
    },
    manage: {
      media: endpoints.manage_media,
      statistics: endpoints.manage_statistics,
      users: endpoints.manage_users,
      comments: endpoints.manage_comments,
      wowzaStatus: endpoints.manage_wowza_status,
      wowzaApplications: endpoints.manage_wowza_applications,
    },
    search: {
      query: endpoints.search + '?q=',
      titles: endpoints.search + '?show=titles&q=',
      tag: endpoints.search + '?t=',
      category: endpoints.search + '?c=',
    },
  });
}

export function endpoints() {
  return ENDPOINTS;
}
