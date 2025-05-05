import React from 'react';
import { ApiUrlConsumer } from '../utils/contexts';
import { MediaListWrapper } from '../components/MediaListWrapper';
import { LazyLoadItemListAsync } from '../components/item-list/LazyLoadItemListAsync.jsx';
import { Page } from './Page';
import { translateString } from '../utils/helpers';
import { ManageAdsPage } from './ManageAdsPage';
import { ManageCategoryAdsPage } from './ManageCategoryAdsPage';

interface AdsTagsPageProps {
  id?: string;
  title?: string;
}

export const AdsTagsPage: React.FC<AdsTagsPageProps> = ({ id = 'adstag', title = translateString('Tags') }) => (
  <Page id={id}>
    <ApiUrlConsumer>
      {(apiUrl) => (
        <MediaListWrapper title={title} className="items-list-ver">
          <LazyLoadItemListAsync singleLinkContent={true} inTagsList={true} requestUrl={apiUrl.archive.adstag} />
        </MediaListWrapper>
      )}
    </ApiUrlConsumer>

    <ManageAdsPage />

    <ManageCategoryAdsPage />
    
  </Page>
);
