import React from 'react';
import { ApiUrlContext } from '../utils/contexts/';
import { csrfToken } from '../utils/helpers/';
import { MaterialIcon, SpinnerLoader } from '../components/_shared';
import { MediaListWrapper } from '../components/MediaListWrapper';
import { Page } from './_Page';
import './ManageWowzaPage.scss';

const WOWZA_APP_NAME_INVALID_RE = /[<>:'"\/\\|?*~]/;
const WOWZA_APP_NAME_INVALID_MESSAGE = 'no puede contener <, >, :, comillas, /, \\, |, ?, *, .. o ~.';

function validateWowzaName(value, label) {
  const normalized = (value || '').trim();

  if (!normalized) {
    return `${label} no puede estar vacío.`;
  }

  if (80 < normalized.length) {
    return `${label} no puede superar 80 caracteres.`;
  }

  if (WOWZA_APP_NAME_INVALID_RE.test(normalized) || -1 < normalized.indexOf('..')) {
    return `${label} ${WOWZA_APP_NAME_INVALID_MESSAGE}`;
  }

  return '';
}

function getErrorMessage(error) {
  if (error && error.message) {
    return error.message;
  }
  return 'No fue posible completar la operación.';
}

function connectionValue(app, field) {
  const streamName = app.stream_name || 'live';

  if ('rtmp_url' === field) {
    return app.rtmp_url || `rtmp://scl.edge.grupoz.cl/${app.name}`;
  }

  if ('stream_name' === field) {
    return streamName;
  }

  if ('publish_username' === field) {
    return app.publish_username || app.name;
  }

  if ('publish_password' === field) {
    return app.publish_password || '';
  }

  if ('hls_url' === field) {
    return app.hls_url || `https://scl.edge.grupoz.cl/${app.name}/${streamName}/playlist.m3u8`;
  }

  return '';
}

function withCacheBuster(url, cacheKey) {
  if (!cacheKey) {
    return url;
  }

  return `${url}${-1 === url.indexOf('?') ? '?' : '&'}refresh=${cacheKey}`;
}

export class ManageWowzaPage extends Page {
  constructor(props) {
    super(props, 'manage-wowza');

    this.state = {
      appName: '',
      scheduleId: '',
      isLoadingStatus: true,
      isLoadingApplications: true,
      isSubmitting: false,
      status: null,
      applications: [],
      applicationsCount: 0,
      applicationsPage: 1,
      applicationsTotalPages: 1,
      result: null,
      activeAppName: '',
      deletingApplicationId: null,
      connectionApplicationId: null,
      connectionSignalReady: false,
      connectionSignalRefreshKey: 0,
      copiedConnectionField: '',
      visiblePasswords: {},
      error: null,
      validationError: '',
    };

    this.loadStatus = this.loadStatus.bind(this);
    this.loadApplications = this.loadApplications.bind(this);
    this.onInputChange = this.onInputChange.bind(this);
    this.onSubmit = this.onSubmit.bind(this);
    this.onDeleteApplication = this.onDeleteApplication.bind(this);
    this.onShowConnection = this.onShowConnection.bind(this);
    this.onTogglePassword = this.onTogglePassword.bind(this);
    this.onCopyConnectionValue = this.onCopyConnectionValue.bind(this);
    this.onRefreshConnectionSignal = this.onRefreshConnectionSignal.bind(this);
    this.onConnectionSignalReady = this.onConnectionSignalReady.bind(this);
  }

  componentDidMount() {
    this.loadStatus();
    this.loadApplications();
  }

  async loadStatus() {
    this.setState({ isLoadingStatus: true });

    try {
      const response = await fetch(ApiUrlContext._currentValue.manage.wowzaStatus, {
        credentials: 'same-origin',
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'Wowza no respondió correctamente.');
      }

      this.setState({
        status: payload.data,
        error: null,
        isLoadingStatus: false,
      });
    } catch (error) {
      this.setState({
        status: null,
        error: getErrorMessage(error),
        isLoadingStatus: false,
      });
    }
  }

  async loadApplications(page) {
    const nextPage = page || this.state.applicationsPage;
    this.setState({ isLoadingApplications: true });

    try {
      const response = await fetch(`${ApiUrlContext._currentValue.manage.wowzaApplications}?page=${nextPage}&page_size=10`, {
        credentials: 'same-origin',
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'No fue posible listar las aplicaciones creadas.');
      }

      this.setState({
        applications: payload.results || [],
        applicationsCount: payload.count || 0,
        applicationsPage: payload.page || 1,
        applicationsTotalPages: payload.total_pages || 1,
        isLoadingApplications: false,
      });
    } catch (error) {
      this.setState({
        applications: [],
        applicationsCount: 0,
        applicationsPage: 1,
        applicationsTotalPages: 1,
        error: getErrorMessage(error),
        isLoadingApplications: false,
      });
    }
  }

  onInputChange(ev) {
    this.setState({
      [ev.currentTarget.name]: ev.currentTarget.value,
      validationError: '',
      result: null,
      error: null,
    });
  }

  async onSubmit(ev) {
    ev.preventDefault();

    const appName = this.state.appName.trim();
    const scheduleId = this.state.scheduleId.trim() || appName;
    const appNameError = validateWowzaName(appName, 'El nombre de la aplicación');
    const scheduleIdError = validateWowzaName(scheduleId, 'El ID schedule SMIL');

    if (appNameError || scheduleIdError) {
      this.setState({
        validationError: appNameError || scheduleIdError,
      });
      return;
    }

    this.setState({
      isSubmitting: true,
      result: null,
      error: null,
      validationError: '',
    });

    try {
      const response = await fetch(ApiUrlContext._currentValue.manage.wowzaApplications, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
        },
        body: JSON.stringify({
          name: appName,
          schedule_id: scheduleId,
        }),
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'Wowza rechazó la solicitud.');
      }

      this.setState({
        appName: '',
        scheduleId: '',
        result: payload,
        activeAppName: appName,
        error: null,
        isSubmitting: false,
      });
      this.loadStatus();
      this.loadApplications(1);
    } catch (error) {
      this.setState({
        error: getErrorMessage(error),
        result: null,
        isSubmitting: false,
      });
    }
  }

  async onDeleteApplication(app) {
    const confirmed = window.confirm(`¿Eliminar la aplicación ${app.name} de Wowza?`);

    if (!confirmed) {
      return;
    }

    this.setState({
      deletingApplicationId: app.id,
      error: null,
      result: null,
    });

    try {
      const response = await fetch(`${ApiUrlContext._currentValue.manage.wowzaApplications}/${app.id}`, {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': csrfToken(),
        },
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'No fue posible eliminar la aplicación.');
      }

      this.setState({
        deletingApplicationId: null,
        activeAppName: this.state.activeAppName === app.name ? '' : this.state.activeAppName,
        connectionApplicationId: this.state.connectionApplicationId === app.id ? null : this.state.connectionApplicationId,
      });
      this.loadApplications(this.state.applicationsPage);
      this.loadStatus();
    } catch (error) {
      this.setState({
        deletingApplicationId: null,
        error: getErrorMessage(error),
      });
    }
  }

  onTogglePassword(appId) {
    this.setState((prevState) => ({
      visiblePasswords: {
        ...prevState.visiblePasswords,
        [appId]: !prevState.visiblePasswords[appId],
      },
    }));
  }

  onShowConnection(app) {
    this.setState({
      connectionApplicationId: app.id,
      connectionSignalReady: false,
      connectionSignalRefreshKey: Date.now(),
      copiedConnectionField: '',
      visiblePasswords: {
        ...this.state.visiblePasswords,
        [app.id]: true,
      },
    });
  }

  onCopyConnectionValue(app, field) {
    const value = connectionValue(app, field);

    if (!value) {
      return;
    }

    const markCopied = () => {
      this.setState({ copiedConnectionField: `${app.id}-${field}` });
      window.setTimeout(() => {
        if (this.state.copiedConnectionField === `${app.id}-${field}`) {
          this.setState({ copiedConnectionField: '' });
        }
      }, 1800);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(markCopied).catch(markCopied);
      return;
    }

    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '-1000px';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    markCopied();
  }

  onRefreshConnectionSignal() {
    this.setState({
      connectionSignalReady: false,
      connectionSignalRefreshKey: Date.now(),
    });
  }

  onConnectionSignalReady() {
    if (!this.state.connectionSignalReady) {
      this.setState({ connectionSignalReady: true });
    }
  }

  renderConnectionField(app, field, label, icon) {
    const value = connectionValue(app, field);
    const copied = this.state.copiedConnectionField === `${app.id}-${field}`;

    return (
      <div className="manage-wowza-connection-card">
        <div className="manage-wowza-connection-card-head">
          <span className="manage-wowza-connection-card-icon">
            <MaterialIcon type={icon} />
          </span>
          <strong>{label}</strong>
        </div>
        <div className="manage-wowza-connection-value">
          <input value={value} readOnly />
          <button type="button" onClick={() => this.onCopyConnectionValue(app, field)} title={`Copiar ${label}`}>
            <MaterialIcon type={copied ? 'check' : 'content_copy'} />
            <span>{copied ? 'Copiado' : 'Copiar'}</span>
          </button>
        </div>
      </div>
    );
  }

  renderConnectionPanel(app) {
    if (!app) {
      return null;
    }

    const hlsUrl = withCacheBuster(connectionValue(app, 'hls_url'), this.state.connectionSignalRefreshKey);

    return (
      <section className="manage-wowza-connection">
        <div className="manage-wowza-connection-head">
          <div>
            <h2>Conexión de {app.name}</h2>
            <span>Señal de monitoreo y credenciales para configurar Wirecast u otro encoder RTMP.</span>
          </div>
          <div className="manage-wowza-connection-head-actions">
            <button type="button" onClick={this.onRefreshConnectionSignal} title="Refrescar señal">
              <MaterialIcon type="refresh" />
            </button>
            <button type="button" onClick={() => this.setState({ connectionApplicationId: null })} title="Cerrar conexión">
              <MaterialIcon type="close" />
            </button>
          </div>
        </div>

        <div className="manage-wowza-signal">
          <video
            key={`${app.id}-${this.state.connectionSignalRefreshKey}`}
            controls
            playsInline
            src={hlsUrl}
            onLoadedData={this.onConnectionSignalReady}
            onCanPlay={this.onConnectionSignalReady}
            onPlaying={this.onConnectionSignalReady}
          />
          <div className={`manage-wowza-signal-placeholder ${this.state.connectionSignalReady ? 'manage-wowza-signal-placeholder-hidden' : ''}`}>
            <span className="manage-wowza-live-icon">
              <MaterialIcon type="radio_button_checked" />
            </span>
            <strong>Señal del stream</strong>
            <span>Si el navegador no reproduce HLS nativo, copia la URL HLS en un reproductor compatible.</span>
          </div>
        </div>

        <div className="manage-wowza-connection-grid">
          {this.renderConnectionField(app, 'rtmp_url', 'RTMP', 'link')}
          {this.renderConnectionField(app, 'stream_name', 'Stream', 'vpn_key')}
          {this.renderConnectionField(app, 'publish_username', 'Usuario', 'person')}
          {this.renderConnectionField(app, 'publish_password', 'Password', 'lock')}
          {this.renderConnectionField(app, 'hls_url', 'Señal HLS', 'live_tv')}
        </div>
      </section>
    );
  }

  pageContent() {
    const {
      appName,
      scheduleId,
      isLoadingStatus,
      isLoadingApplications,
      isSubmitting,
      status,
      applications,
      applicationsCount,
      applicationsPage,
      applicationsTotalPages,
      result,
      activeAppName,
      deletingApplicationId,
      connectionApplicationId,
      visiblePasswords,
      error,
      validationError,
    } = this.state;
    const previewAppName = appName.trim() || 'nombre_app';
    const previewScheduleId = scheduleId.trim() || previewAppName;
    const connectionApplication = applications.find((app) => app.id === connectionApplicationId);

    return (
      <MediaListWrapper className="items-list-hor manage-wowza-wrapper">
        <div className="manage-wowza-page">
          <div className="manage-wowza-head">
            <div>
              <h1>Wowza control</h1>
              <p>Crear aplicaciones live y aplicar módulos operativos de Stream Publisher y Push Publish.</p>
            </div>
            <button className="manage-wowza-refresh" onClick={this.loadStatus} disabled={isLoadingStatus}>
              <MaterialIcon type="refresh" />
              <span>Actualizar estado</span>
            </button>
          </div>

          <div className={`manage-wowza-status ${status ? 'manage-wowza-status-available' : 'manage-wowza-status-unavailable'}`}>
            <div className="manage-wowza-status-icon">
              {isLoadingStatus ? <SpinnerLoader size="small" /> : <MaterialIcon type={status ? 'check_circle' : 'error'} />}
            </div>
            <div>
              <strong>{status ? 'Wowza API disponible' : isLoadingStatus ? 'Consultando Wowza' : 'Wowza API no disponible'}</strong>
              <span>
                {status
                  ? 'El panel puede crear aplicaciones en el servidor configurado.'
                  : isLoadingStatus
                  ? 'Validando conectividad con el API Manager.'
                  : 'Revisa conectividad, credenciales o permisos del API Manager.'}
              </span>
            </div>
          </div>

          <div className="manage-wowza-layout">
            <form className="manage-wowza-form" onSubmit={this.onSubmit}>
              <div className="manage-wowza-form-head">
                <MaterialIcon type="settings_input_antenna" />
                <h2>Nueva aplicación live</h2>
              </div>

              <label>
                Nombre de aplicación
                <input
                  name="appName"
                  value={appName}
                  onChange={this.onInputChange}
                  placeholder="eventoz06"
                  autoComplete="off"
                />
              </label>

              <label>
                ID schedule SMIL
                <input
                  name="scheduleId"
                  value={scheduleId}
                  onChange={this.onInputChange}
                  placeholder={previewAppName}
                  autoComplete="off"
                />
              </label>

              {validationError ? <div className="manage-wowza-message manage-wowza-message-error">{validationError}</div> : null}
              {error ? <div className="manage-wowza-message manage-wowza-message-error">{error}</div> : null}
              {result ? <div className="manage-wowza-message manage-wowza-message-success">Aplicación creada y configurada correctamente.</div> : null}

              <button className="manage-wowza-submit" type="submit" disabled={isSubmitting}>
                {isSubmitting ? <SpinnerLoader size="small" /> : <MaterialIcon type="add_circle" />}
                <span>{isSubmitting ? 'Creando aplicación' : 'Crear aplicación'}</span>
              </button>
            </form>

            <section className="manage-wowza-preview">
              <div className="manage-wowza-preview-head">
                <MaterialIcon type="rule" />
                <h2>Configuración aplicada</h2>
              </div>
              <dl>
                <dt>Tipo</dt>
                <dd>Live</dd>
                <dt>Stream type</dt>
                <dd>live</dd>
                <dt>HLS packetizer</dt>
                <dd>cupertinostreamingpacketizer</dd>
                <dt>HTTP streamer</dt>
                <dd>cupertinostreaming</dd>
                <dt>SMIL schedule</dt>
                <dd>{`streamschedule-${previewScheduleId}.smil`}</dd>
                <dt>Módulos</dt>
                <dd>Core, Logging, FLVPlayback, StreamPublisher, PushPublish</dd>
              </dl>
            </section>
          </div>

          <section className="manage-wowza-apps">
            <div className="manage-wowza-apps-head">
              <div>
                <h2>Aplicaciones creadas en la plataforma</h2>
                <span>{applicationsCount ? `${applicationsCount} aplicaciones guardadas` : 'Sin aplicaciones guardadas'}</span>
              </div>
              {activeAppName ? <strong>Última creada: {activeAppName}</strong> : null}
            </div>

            {isLoadingApplications ? (
              <div className="manage-wowza-apps-empty">
                <SpinnerLoader size="small" />
                <span>Cargando aplicaciones</span>
              </div>
            ) : applications.length ? (
              <React.Fragment>
                <div className="manage-wowza-apps-list">
                  <div className="manage-wowza-app-row manage-wowza-app-row-head">
                    <span>Aplicación</span>
                    <span>SMIL</span>
                    <span>Usuario</span>
                    <span>Password</span>
                    <span>Estado</span>
                    <span>Acciones</span>
                  </div>
                  {applications.map((app) => (
                    <div className={`manage-wowza-app-row ${connectionApplicationId === app.id || activeAppName === app.name ? 'manage-wowza-app-row-active' : ''}`} key={app.id || app.name}>
                      <span>
                        <MaterialIcon type={connectionApplicationId === app.id || activeAppName === app.name ? 'radio_button_checked' : 'radio_button_unchecked'} />
                        <strong>{app.name}</strong>
                      </span>
                      <span>{`streamschedule-${app.schedule_id}.smil`}</span>
                      <span>{app.publish_username || app.name}</span>
                      <span>
                        <span className="manage-wowza-secret">
                          <span>{visiblePasswords[app.id] ? app.publish_password : '************'}</span>
                          <button type="button" onClick={() => this.onTogglePassword(app.id)} title={visiblePasswords[app.id] ? 'Ocultar password' : 'Ver password'}>
                            <MaterialIcon type={visiblePasswords[app.id] ? 'visibility_off' : 'visibility'} />
                          </button>
                        </span>
                      </span>
                      <span>{app.is_active ? 'Activa' : 'Inactiva'}</span>
                      <span>
                        <span className="manage-wowza-row-actions">
                          <button className="manage-wowza-connect" type="button" onClick={() => this.onShowConnection(app)} title="Ver conexión">
                            <MaterialIcon type="settings_input_hdmi" />
                            <span>Conexión</span>
                          </button>
                          <button
                            className="manage-wowza-delete"
                            type="button"
                            onClick={() => this.onDeleteApplication(app)}
                            disabled={deletingApplicationId === app.id}
                            title="Eliminar aplicación"
                          >
                            {deletingApplicationId === app.id ? <SpinnerLoader size="small" /> : <MaterialIcon type="delete" />}
                            <span>{deletingApplicationId === app.id ? 'Eliminando' : 'Eliminar'}</span>
                          </button>
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
                <div className="manage-wowza-pagination">
                  <button type="button" onClick={() => this.loadApplications(applicationsPage - 1)} disabled={applicationsPage <= 1}>
                    <MaterialIcon type="chevron_left" />
                    <span>Anterior</span>
                  </button>
                  <strong>
                    Página {applicationsPage} de {applicationsTotalPages}
                  </strong>
                  <button type="button" onClick={() => this.loadApplications(applicationsPage + 1)} disabled={applicationsPage >= applicationsTotalPages}>
                    <span>Siguiente</span>
                    <MaterialIcon type="chevron_right" />
                  </button>
                </div>
              </React.Fragment>
            ) : (
              <div className="manage-wowza-apps-empty">
                <MaterialIcon type="info" />
                <span>Crea una aplicación para verla en este listado.</span>
              </div>
            )}
          </section>

          {this.renderConnectionPanel(connectionApplication)}

          {result ? (
            <section className="manage-wowza-result">
              <h2>Respuesta Wowza</h2>
              <pre>{JSON.stringify(result, null, 2)}</pre>
            </section>
          ) : null}
        </div>
      </MediaListWrapper>
    );
  }
}
