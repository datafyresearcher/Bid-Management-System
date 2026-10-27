import BrandLoader from "../components/Loading";

// Shown while a route's code is on its way (client-side navigation): the
// sidebar stays put and the content area shows the spinner instead of a
// blank gap.
export default function Loading() {
  return <BrandLoader />;
}
