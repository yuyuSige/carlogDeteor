# Binder / IPC

Symptoms that count as BINDER_IPC (need the line as evidence):

- `DeadObjectException`, `binderDied`, `!!! FAILED BINDER TRANSACTION !!!`
- `RemoteException`, `TransactionTooLargeException`
- `onServiceDisconnected` / `onServiceDisConnected`

E02 AIDL (read-only knowledge): `IAvmSdkService`, `IAvmSdkListener`, Kanzi `IDataService` / `ICallback`.

Causal pattern:

```
connection established → binder transaction failed → service disconnected → retry failed
```
